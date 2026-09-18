"""Shared validation and presentation rules for both WMS adapters."""

from datetime import date, datetime, time, timedelta, timezone

from django.utils import timezone as django_timezone

RESOURCES = frozenset({"stock", "orders", "receivings", "shipments", "movements"})
ACTIVE_ORDERS = frozenset({"new", "confirmed", "picking", "packed"})
ACTIVE_RECEIVINGS = frozenset({"draft", "confirmed", "in_receiving"})


def pagination(page: int, page_size: int) -> tuple[int, int]:
    if isinstance(page, bool) or isinstance(page_size, bool):
        raise ValueError("Некорректная пагинация")
    if not isinstance(page, int) or not isinstance(page_size, int):
        raise ValueError("Параметры пагинации должны быть целыми числами")
    if not 1 <= page <= 1000 or not 1 <= page_size <= 100:
        raise ValueError("Страница: 1–1000, размер страницы: 1–100")
    return page_size + 1, (page - 1) * page_size


def paginated(rows: list[dict], page: int, page_size: int) -> dict:
    return {"results": rows[:page_size], "page": page, "page_size": page_size,
            "has_next": len(rows) > page_size}


def as_datetime(value: str | date | datetime) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if not isinstance(value, datetime):
        raise ValueError("Дата должна быть в формате ISO 8601")
    # A bare date means midnight UTC. Naive date/time input is also interpreted
    # as UTC at this API boundary; stored WMS timestamps remain timezone-aware.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def date_range(date_from=None, date_to=None, *, now=None) -> tuple[datetime, datetime]:
    end = as_datetime(date_to) if date_to is not None else (now or django_timezone.now())
    start = as_datetime(date_from) if date_from is not None else end - timedelta(days=90)
    if end <= start or end - start > timedelta(days=90):
        raise ValueError("Диапазон дат должен быть положительным и не больше 90 дней")
    return start, end


def stock_totals(total: int, reserved: int) -> dict:
    return {"total": total, "reserved": reserved, "available": total - reserved}


def attention(counts: dict) -> list[dict]:
    rules = (
        ("overdue_tasks", "Есть просроченные задания склада"),
        ("deadline_orders", "Есть заказы с близким или прошедшим сроком отгрузки"),
        ("pending_requests", "Есть необработанные заявки из личного кабинета"),
        ("receiving_in_progress", "Идёт приёмка товара"),
        ("integration_errors", "Есть ошибки интеграций"),
        ("stale_integrations", "Интеграция давно не синхронизировалась"),
    )
    return [{"code": code, "message": message, "count": int(counts[code])}
            for code, message in rules if counts.get(code, 0)]
