from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.db import DatabaseError

from wms import queries
from wms.mock import MockRepository
from wms.repository import PostgresRepository, get_repository
from wms.services import as_datetime, date_range, stock_totals

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def test_mock_search_pagination_and_isolation():
    repository = MockRepository(now=NOW)
    first = repository.clients(page_size=2)
    second = repository.clients(page=2, page_size=2)
    assert first["has_next"] is True
    assert second["has_next"] is False
    assert len({row["id"] for row in first["results"] + second["results"]}) == 4
    assert repository.clients("РОМАШКА")["results"][0]["id"] == 1
    assert repository.clients("7700000002")["results"][0]["id"] == 2
    assert repository.clients("%'")["results"] == []
    first["results"][0]["name"] = "changed"
    assert repository.client(first["results"][0]["id"])["name"] != "changed"
    assert repository.client(999) is None


def test_summary_current_stock_old_active_orders_and_billing_reversal(settings):
    settings.INTEGRATION_STALE_HOURS = 1
    settings.DEADLINE_WARNING_HOURS = 24
    repository = MockRepository(now=NOW)
    summary = repository.summary(1)
    assert summary["stock"] == {"total": 330, "reserved": 60, "available": 270}
    assert summary["active_orders"] == 2  # Includes the 120-day-old open order.
    assert summary["active_receivings"] == 1
    assert summary["shipments"] == 1
    assert Decimal(summary["billing_total"]) == Decimal("1500.00")
    assert {item["code"] for item in summary["attention"]} == {
        "overdue_tasks", "deadline_orders", "pending_requests", "receiving_in_progress",
        "integration_errors", "stale_integrations",
    }
    moves = repository.data["movements_movement"]
    expected = sum(r["quantity"] for r in moves if r["product_id"] in {11, 12}
                   and r["movement_type"] == "shipment" and r["reversal_of_id"] is None)
    assert summary["shipped_units"] == expected
    assert not any(a["code"] == "integration_errors" for a in repository.summary(2)["attention"])


def test_daily_snapshot_uses_day_instead_of_rolling_90_days():
    repository = MockRepository(now=NOW)
    day = NOW.date() - timedelta(days=1)
    snapshot = repository.metric_snapshot(1, day)
    moves = repository.data["movements_movement"]
    expected = sum(r["quantity"] for r in moves if r["product_id"] in {11, 12}
                   and as_datetime(r["created_at"]).date() == day
                   and r["movement_type"] == "receiving" and r["reversal_of_id"] is None)
    assert snapshot["received_units"] == expected
    assert snapshot["stock_available"] == 270
    assert snapshot["received_units"] < repository.summary(1)["received_units"]


def test_movements_are_paginated_and_belong_to_selected_client():
    repository = MockRepository(now=NOW)
    first = repository.detail(2, "movements", page_size=50)
    second = repository.detail(2, "movements", page=2, page_size=50)
    assert len(first["results"]) == 50 and first["has_next"]
    assert len(second["results"]) == 22 and not second["has_next"]
    assert all(r["product_id"] in {21, 22} for r in first["results"] + second["results"])
    start, end = NOW - timedelta(hours=3), NOW - timedelta(hours=1)
    filtered = repository.detail(2, "movements", date_from=start, date_to=end)["results"]
    assert len(filtered) == 2
    assert all(start <= as_datetime(r["created_at"]) < end for r in filtered)


@pytest.mark.parametrize("page,size", [(0, 50), (1, 0), (1001, 50), (1, 101), (True, 50)])
def test_invalid_pagination_is_rejected_before_queries(page, size):
    with pytest.raises(ValueError):
        PostgresRepository().clients(page=page, page_size=size)
    with pytest.raises(ValueError):
        MockRepository(now=NOW).clients(page=page, page_size=size)


def test_date_validation_and_current_stock_semantics():
    start, end = date_range("2026-09-01", "2026-09-02")
    assert start.tzinfo == timezone.utc and end - start == timedelta(days=1)
    with pytest.raises(ValueError):
        date_range("2026-01-01", "2026-09-02")
    with pytest.raises(ValueError):
        date_range("2026-09-02", "2026-09-01")
    assert MockRepository(now=NOW).detail(1, "stock", date_from="2020-01-01")["results"]
    assert stock_totals(5, 7)["available"] == -2  # Do not silently clamp WMS data.


@pytest.fixture
def connection(monkeypatch):
    cursor = MagicMock()
    cursor.description = [("id",), ("name",), ("inn",), ("is_active",)]
    cursor.fetchall.return_value = [(1, "Ромашка", "7700000001", True)]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr("wms.repository.connections", {"wms": connection})
    return cursor


def test_postgres_parameterization_and_bounded_fetch(connection):
    malicious = "x' OR 1=1 --_%"
    PostgresRepository().clients(malicious, page=3, page_size=10)
    sql, params = connection.execute.call_args.args
    assert malicious not in sql
    assert params[-2:] == [11, 20]
    assert params[0] == "%x' OR 1=1 --\\_\\%%"
    assert "public.clients_client" in sql and "LIMIT %s OFFSET %s" in sql
    PostgresRepository().detail(42, "movements", page_size=25,
                                date_from="2026-09-01", date_to="2026-09-02")
    sql, params = connection.execute.call_args.args
    assert params[0] == 42 and params[-2:] == [26, 0]
    assert "p.client_id = %s" in sql and "m.created_at >= %s" in sql
    assert "public.movements_movement" in sql and "public.products_product" in sql


def test_read_only_guard_and_resource_allowlist(connection):
    repository = PostgresRepository()
    for unsafe in ("DELETE FROM public.clients_client", "SELECT 1; DROP TABLE x", ""):
        with pytest.raises(ValueError):
            repository._rows(unsafe, [])
    with pytest.raises(ValueError):
        repository.detail(1, "orders; DROP TABLE x")
    connection.execute.assert_not_called()


@pytest.mark.parametrize("sql", [queries.DOCUMENT_SUMMARY, queries.ATTENTION, "SELECT\n 1"])
def test_read_only_guard_allows_newline_after_select(connection, sql):
    PostgresRepository()._rows(sql, [])
    connection.execute.assert_called_once_with(sql, [])


def test_database_errors_propagate_without_logging_credentials(connection, caplog):
    connection.execute.side_effect = DatabaseError("password=do-not-log")
    with pytest.raises(DatabaseError):
        PostgresRepository().client(1)
    assert "WMS query failed: DatabaseError" in caplog.text
    assert "do-not-log" not in caplog.text


def test_postgres_summary_uses_aggregates_and_original_movement_filter(monkeypatch):
    repository = PostgresRepository()
    calls = []
    answers = {
        queries.STOCK_SUMMARY: {"total": 10, "reserved": 4},
        queries.DOCUMENT_SUMMARY: {"active_orders": 3, "active_receivings": 1,
                                  "receiving_in_progress": 1, "shipments": 2},
        queries.MOVEMENT_SUMMARY: {"received_units": 12, "shipped_units": 8},
        queries.BILLING_SUMMARY: {"billing_total": Decimal("21.50")},
        queries.ATTENTION: {"overdue_tasks": 0, "deadline_orders": 1, "pending_requests": 0,
                            "integration_errors": 0, "stale_integrations": 0},
        queries.CLIENT: {"id": 7, "name": "Client", "inn": "", "is_active": True},
    }

    def rows(sql, params):
        calls.append((sql, params))
        return [dict(answers[sql])]

    monkeypatch.setattr(repository, "_rows", rows)
    result = repository.summary(7)
    assert result["stock"]["available"] == 6
    assert result["billing_total"] == "21.50"
    assert all(params[0] == 7 for _, params in calls)
    flow = next(params for sql, params in calls if sql == queries.MOVEMENT_SUMMARY)
    assert flow[2] - flow[1] == timedelta(days=90)
    assert "m.reversal_of_id IS NULL" in queries.MOVEMENT_SUMMARY
    assert "reversal_of_id" not in queries.BILLING_SUMMARY
    assert "created_at" not in queries.DOCUMENT_SUMMARY


def test_factory_selects_explicit_mode(settings):
    settings.WMS_MODE = "mock"
    assert isinstance(get_repository(), MockRepository)
    settings.WMS_MODE = "postgres"
    assert isinstance(get_repository(), PostgresRepository)
    settings.WMS_MODE = "invalid"
    with pytest.raises(ValueError):
        get_repository()
