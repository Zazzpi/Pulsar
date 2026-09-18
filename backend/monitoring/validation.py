import json
from datetime import date, timedelta

from django.utils import timezone


class InvalidInput(Exception):
    pass


def positive_int(value, name, maximum=2**63 - 1):
    try:
        if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
            raise ValueError
        result = int(value)
        if result < 1 or result > maximum:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise InvalidInput(f"{name}: требуется число от 1 до {maximum}.") from None


def pagination(request):
    return (
        positive_int(request.GET.get("page", "1"), "page", 1000),
        positive_int(request.GET.get("page_size", "50"), "page_size", 100),
    )


def date_range(request):
    """ISO calendar dates in UTC, inclusive start and exclusive end, <=90 days."""
    end = timezone.now().date() + timedelta(days=1)
    start = end - timedelta(days=90)
    try:
        if "to" in request.GET:
            end = date.fromisoformat(request.GET["to"])
            if request.GET["to"] != end.isoformat():
                raise ValueError
            start = end - timedelta(days=90)
        if "from" in request.GET:
            start = date.fromisoformat(request.GET["from"])
            if request.GET["from"] != start.isoformat():
                raise ValueError
        if not 1 <= (end - start).days <= 90:
            raise ValueError
    except ValueError:
        raise InvalidInput("Период from/to: даты YYYY-MM-DD, from < to, не более 90 дней; to не включается.") from None
    return start, end


def json_body(request):
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, TypeError):
        raise InvalidInput("Ожидается JSON-объект.") from None
