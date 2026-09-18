"""Read-only PostgreSQL repository. Database privileges enforce the boundary."""

import logging
from datetime import date, timedelta
from time import monotonic

from django.conf import settings
from django.db import DatabaseError, connections
from django.utils import timezone

from . import queries
from .services import RESOURCES, as_datetime, attention, date_range, paginated, pagination, stock_totals

logger = logging.getLogger(__name__)


class PostgresRepository:
    """Every operation targets the dedicated ``wms`` database alias.

    Use a PostgreSQL role with SELECT grants only and configure connection OPTIONS
    for default_transaction_read_only and statement_timeout. No WMS models or
    migrations are used. The SELECT guard is defense in depth, not a SQL parser.
    """

    def _rows(self, sql: str, params: list) -> list[dict]:
        if not sql.split() or sql.split()[0].upper() != "SELECT" or ";" in sql:
            raise ValueError("WMS repository accepts a single SELECT statement only")
        started = monotonic()
        try:
            with connections["wms"].cursor() as cursor:
                cursor.execute(sql, params)
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]
        except DatabaseError as exc:
            # Do not log parameters, connection strings, or driver exception text.
            logger.error("WMS query failed: %s", type(exc).__name__)
            raise
        finally:
            elapsed = monotonic() - started
            if elapsed >= getattr(settings, "WMS_SLOW_QUERY_SECONDS", 1.0):
                logger.warning("Slow WMS query: %.3f seconds", elapsed)

    def clients(self, search: str = "", page: int = 1, page_size: int = 50) -> dict:
        limit, offset = pagination(page, page_size)
        # LIKE wildcards supplied by the user are literal characters.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped + "%"
        return paginated(self._rows(queries.CLIENTS, [pattern, pattern, limit, offset]),
                         page, page_size)

    def client(self, client_id: int) -> dict | None:
        rows = self._rows(queries.CLIENT, [client_id])
        return rows[0] if rows else None

    def detail(self, client_id: int, resource: str, page: int = 1,
               page_size: int = 50, date_from=None, date_to=None) -> dict:
        if resource not in RESOURCES:
            raise ValueError("Неизвестный раздел WMS")
        limit, offset = pagination(page, page_size)
        params = [client_id]
        if resource != "stock":
            params.extend(date_range(date_from, date_to))
        params.extend([limit, offset])
        return paginated(self._rows(queries.DETAILS[resource], params), page, page_size)

    def summary(self, client_id: int) -> dict:
        now = timezone.now()
        start = now - timedelta(days=90)
        stock = self._rows(queries.STOCK_SUMMARY, [client_id])[0]
        documents = self._rows(queries.DOCUMENT_SUMMARY,
                               [client_id] * 4 + [start, now])[0]
        movements = self._rows(queries.MOVEMENT_SUMMARY, [client_id, start, now])[0]
        billing = self._rows(queries.BILLING_SUMMARY, [client_id, start, now])[0]
        deadline = now + timedelta(hours=getattr(settings, "DEADLINE_WARNING_HOURS", 24))
        stale = now - timedelta(hours=getattr(settings, "INTEGRATION_STALE_HOURS", 1))
        counts = self._rows(queries.ATTENTION,
                            [client_id, now, client_id, deadline, client_id,
                             client_id, client_id, client_id, stale])[0]
        counts["receiving_in_progress"] = documents.pop("receiving_in_progress")
        return {"client": self.client(client_id), "stock": stock_totals(**stock),
                **documents, **movements, "billing_total": str(billing["billing_total"]),
                "attention": attention(counts), "updated_at": now.isoformat()}

    def metric_snapshot(self, client_id: int, day: date) -> dict:
        """Store daily flows alongside stock/activity observed at capture time."""
        start = as_datetime(day)
        end = start + timedelta(days=1)
        stock = self._rows(queries.STOCK_SUMMARY, [client_id])[0]
        documents = self._rows(queries.DOCUMENT_SUMMARY, [client_id] * 4 + [start, end])[0]
        movements = self._rows(queries.MOVEMENT_SUMMARY, [client_id, start, end])[0]
        return {**{f"stock_{key}": value for key, value in stock_totals(**stock).items()},
                "active_orders": documents["active_orders"],
                "active_receivings": documents["active_receivings"], **movements}


def get_repository():
    mode = getattr(settings, "WMS_MODE", "mock")
    if mode == "mock":
        from .mock import MockRepository
        return MockRepository()
    if mode == "postgres":
        return PostgresRepository()
    raise ValueError("WMS_MODE must be mock or postgres")
