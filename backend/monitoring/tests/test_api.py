import hashlib
from datetime import date, timedelta
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import Client
from django.utils import timezone

from accounts.models import ApiToken
from config.routers import ApplicationRouter
from monitoring.models import ClientDailyMetric, ClientNote, ClientWatch
from monitoring.services import cached_read

pytestmark = pytest.mark.django_db


def test_login_digest_logout(user):
    client = Client(enforce_csrf_checks=True)
    response = client.post("/api/auth/login/", {
        "username": user.username, "password": "A-test-passphrase-218",
    }, content_type="application/json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"] == {"id": user.pk, "username": user.username}
    token = ApiToken.objects.get()
    assert token.digest == hashlib.sha256(payload["token"].encode()).hexdigest()
    assert token.digest != payload["token"]
    client.defaults["HTTP_AUTHORIZATION"] = "Bearer " + payload["token"]
    assert client.get("/api/clients/").status_code == 200
    assert client.post("/api/auth/logout/").status_code == 200
    assert client.get("/api/clients/").status_code == 401


@pytest.mark.parametrize("path", [
    "/api/clients/", "/api/clients/1/summary/", "/api/clients/1/stock/",
    "/api/clients/1/orders/", "/api/clients/1/receivings/", "/api/clients/1/shipments/",
    "/api/clients/1/movements/", "/api/clients/1/notes/", "/api/clients/1/metrics/", "/api/watches/",
])
def test_every_data_endpoint_requires_bearer(path):
    response = Client().get(path)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"


def test_expired_and_inactive_tokens_rejected(api, user):
    ApiToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert api.get("/api/watches/").status_code == 401
    ApiToken.objects.update(expires_at=timezone.now() + timedelta(hours=1))
    user.is_active = False
    user.save()
    assert api.get("/api/watches/").status_code == 401


def test_login_validation_and_rate_limit(user, settings):
    client = Client()
    assert client.post("/api/auth/login/", "[]", content_type="application/json").status_code == 400
    settings.LOGIN_RATE_LIMIT = 2
    body = {"username": user.username, "password": "incorrect"}
    assert client.post("/api/auth/login/", body, content_type="application/json").status_code == 401
    assert client.post("/api/auth/login/", body, content_type="application/json").status_code == 401
    response = client.post("/api/auth/login/", body, content_type="application/json")
    assert response.status_code == 429
    assert response["Retry-After"] == "300"


def test_watch_exact_duration_idempotence_and_isolation(api, other_api, user):
    response = api.post("/api/watches/", {"wms_client_id": 1}, content_type="application/json")
    assert response.status_code == 201
    item = response.json()
    watch = ClientWatch.objects.get(pk=item["id"])
    assert watch.user == user
    assert watch.ends_at - watch.started_at == timedelta(days=90)
    assert timezone.is_aware(watch.started_at)
    repeat = api.post("/api/watches/", {"wms_client_id": 1}, content_type="application/json")
    assert repeat.status_code == 200
    assert repeat.json()["id"] == watch.pk
    assert repeat.json()["ends_at"] == item["ends_at"]
    assert other_api.get("/api/watches/").json()["results"] == []
    assert other_api.delete(f"/api/watches/{watch.pk}/").status_code == 404
    assert api.get("/api/watches/?wms_client_id=2").json()["results"] == []
    assert len(api.get("/api/watches/?wms_client_id=1").json()["results"]) == 1
    assert api.delete(f"/api/watches/{watch.pk}/").status_code == 200
    assert api.get("/api/watches/").json()["results"] == []


def test_expired_watch_can_be_restarted(api, user):
    now = timezone.now()
    old = ClientWatch.objects.create(
        user=user, wms_client_id=1, started_at=now - timedelta(days=91),
        ends_at=now - timedelta(days=1),
    )
    assert api.get("/api/watches/").json()["results"][0]["is_active"] is False
    response = api.post("/api/watches/", {"wms_client_id": 1}, content_type="application/json")
    assert response.status_code == 201
    assert response.json()["id"] != old.pk
    old.refresh_from_db()
    assert old.is_active is False


def test_notes_are_user_scoped_and_paginated(api, other_api):
    for body in ("First", "Second"):
        response = api.post("/api/clients/1/notes/", {"body": body}, content_type="application/json")
        assert response.status_code == 201
    response = api.get("/api/clients/1/notes/?page_size=1").json()
    assert response["has_next"] is True
    assert response["results"][0]["body"] == "Second"
    assert other_api.get("/api/clients/1/notes/").json()["results"] == []
    assert api.get("/api/clients/2/notes/").json()["results"] == []
    assert ClientNote.objects.count() == 2


@pytest.mark.parametrize("body", ["", " ", "x" * 5001, None, 42])
def test_invalid_notes(api, body):
    assert api.post("/api/clients/1/notes/", {"body": body}, content_type="application/json").status_code == 400


@pytest.mark.parametrize("query", ["page=0", "page=-1", "page=1001", "page=abc", "page_size=101", "page_size=0"])
def test_pagination_bounds(api, query):
    assert api.get("/api/clients/?" + query).status_code == 400


def test_client_search_pagination_and_summary(api):
    first = api.get("/api/clients/?page_size=2").json()
    second = api.get("/api/clients/?page_size=2&page=2").json()
    assert len(first["results"]) == len(second["results"]) == 2
    assert first["has_next"] is True
    assert second["has_next"] is False
    assert not {row["id"] for row in first["results"]} & {row["id"] for row in second["results"]}
    assert len(api.get("/api/clients/?q=7700000001").json()["results"]) == 1
    summary = api.get("/api/clients/1/summary/").json()
    assert summary["client"]["id"] == 1
    assert float(summary["stock"]["available"]) == float(summary["stock"]["total"]) - float(summary["stock"]["reserved"])
    assert api.get("/api/clients/999/summary/").status_code == 404
    assert api.post("/api/watches/", {"wms_client_id": 999}, content_type="application/json").status_code == 404


@pytest.mark.parametrize("query", [
    "from=2026-01-01&to=2026-05-01", "from=not-a-date", "from=2026-99-01",
    "from=2026-01-01&to=2026-01-01", "from=2026-01-02&to=2026-01-01", "from=20260101",
])
def test_history_date_validation(api, query):
    assert api.get("/api/clients/1/movements/?" + query).status_code == 400


def test_history_pagination_bounded_dates(api):
    with patch("monitoring.services.get_repository") as factory:
        repo = factory.return_value
        repo.client.return_value = {"id": 1}
        repo.detail.return_value = {"results": [], "page": 1, "page_size": 50, "has_next": False}
        assert api.get("/api/clients/1/movements/?from=2026-01-01&to=2026-04-01").status_code == 200
        assert repo.detail.call_args.kwargs["date_from"] == date(2026, 1, 1)
        assert repo.detail.call_args.kwargs["date_to"] == date(2026, 4, 1)
    response = api.get("/api/clients/1/stock/?from=2026-01-01&to=2026-04-01")
    assert response.status_code == 400


def test_cache_separates_filters_and_hits(api):
    with patch("monitoring.services.get_repository") as factory:
        repo = factory.return_value
        repo.client.return_value = {"id": 1}
        repo.summary.return_value = {"client": {"id": 1}, "stock": {"available": 12}}
        for _ in range(2):
            assert api.get("/api/clients/1/summary/").status_code == 200
        assert repo.client.call_count == repo.summary.call_count == 1
        repo.detail.return_value = {"results": [], "page": 1, "page_size": 50, "has_next": False}
        for query in ("page=1", "page=1", "page=2", "page=2&page_size=25"):
            assert api.get("/api/clients/1/movements/?" + query).status_code == 200
        assert repo.detail.call_count == 3
        api.get("/api/clients/1/movements/?from=2026-01-01&to=2026-02-01")
        assert repo.detail.call_count == 4


def test_cache_timeout_uses_setting(settings):
    settings.CACHE_TTLS = {**settings.CACHE_TTLS, "summary": 17}
    with patch("monitoring.services.get_repository") as factory, patch("monitoring.services.cache.set") as set_cache:
        factory.return_value.summary.return_value = {"stock": {"available": 1}}
        cached_read("summary", client_id=1)
        assert set_cache.call_args.kwargs["timeout"] == 17


def test_upstream_errors_are_safe_json_and_logged(api, caplog):
    with patch("monitoring.services.get_repository", side_effect=RuntimeError("password=NeverPrintThis")):
        response = api.get("/api/clients/")
    assert response.status_code == 503
    assert "NeverPrintThis" not in response.content.decode()
    assert "NeverPrintThis" not in caplog.text
    assert "WMS read failed" in caplog.text


def test_cache_failure_falls_back_to_repository(api, caplog):
    with patch("monitoring.services.cache.get", side_effect=RuntimeError("secret-cache-password")):
        response = api.get("/api/clients/")
    assert response.status_code == 200
    assert "secret-cache-password" not in caplog.text
    assert "Cache read failed" in caplog.text


def test_app_database_failure_sanitized(api, caplog):
    with patch("accounts.authentication.ApiToken.objects.select_related", side_effect=OperationalError("secret-db-password")):
        response = api.get("/api/watches/")
    assert response.status_code == 503
    assert "secret-db-password" not in caplog.text + response.content.decode()


def test_public_health_and_secure_redirect(settings):
    settings.SECURE_SSL_REDIRECT = True
    client = Client()
    assert client.get("/api/health/").status_code == 200
    assert client.get("/api/clients/").status_code == 301
    assert client.get("/api/clients/", secure=True).status_code == 401


def test_wms_migrations_refused_before_connection():
    assert ApplicationRouter().allow_migrate("wms", "monitoring") is False
    with pytest.raises(CommandError, match="only.*default"):
        call_command("migrate", database="wms", stdout=StringIO())


def test_daily_snapshots_distinct_clients_and_idempotent(user, other_user, api):
    now = timezone.now()
    for owner in (user, other_user):
        ClientWatch.objects.create(user=owner, wms_client_id=1, started_at=now, ends_at=now + timedelta(days=90))
    values = {
        "stock_total": 100, "stock_reserved": 20, "stock_available": 80,
        "received_units": 3, "shipped_units": 4, "active_orders": 2, "active_receivings": 1,
    }
    repo = Mock()
    repo.metric_snapshot.return_value = values
    with patch("monitoring.management.commands.snapshot_metrics.get_repository", return_value=repo):
        call_command("snapshot_metrics", stdout=StringIO())
        assert repo.metric_snapshot.call_count == 1
        assert repo.metric_snapshot.call_args.args == (1, now.date())
        call_command("snapshot_metrics", stdout=StringIO())
    assert ClientDailyMetric.objects.count() == 1
    metric = ClientDailyMetric.objects.get()
    assert metric.received_units == 3
    assert len(api.get("/api/clients/1/metrics/").json()["results"]) == 1


def test_demo_command_requires_mock_and_env(settings, monkeypatch):
    settings.WMS_MODE = "postgres"
    with pytest.raises(CommandError, match="mock"):
        call_command("create_demo_user")
    settings.WMS_MODE = "mock"
    monkeypatch.delenv("DEMO_USERNAME", raising=False)
    with pytest.raises(CommandError, match="DEMO_USERNAME"):
        call_command("create_demo_user")
