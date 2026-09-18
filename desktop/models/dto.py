from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class CachedResponse:
    payload: Any
    updated_at: str


def display_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return str(value)


def watch_caption(watch: dict | None) -> str:
    if not watch:
        return "Клиент не находится под наблюдением"
    try:
        start = datetime.fromisoformat(watch["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(watch["ends_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        elapsed = max(0, min(90, (now - start).days))
        state = "Наблюдение" if watch.get("is_active") and now < end else "Наблюдение завершено"
        return f"{state}: {elapsed} / 90 дней; до {display_time(watch['ends_at'])}"
    except (KeyError, ValueError, TypeError):
        return "Наблюдение: дата недоступна"
