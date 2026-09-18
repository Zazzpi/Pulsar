"""Desktop configuration contains API settings only, never WMS credentials."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalize_origin(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Укажите полный адрес API: https://server.example")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Адрес API не должен содержать пароль, параметры или фрагмент.")
    if parts.path.rstrip("/"):
        raise ValueError("Укажите адрес сервера без /api/ и других путей.")
    if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Для удалённого сервера требуется HTTPS.")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Некорректный порт API.") from exc
    hostname = parts.hostname.lower()
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port and not (parts.scheme == "http" and port == 80 or parts.scheme == "https" and port == 443):
        authority += f":{port}"
    return urlunsplit((parts.scheme.lower(), authority, "", "", ""))


@dataclass(frozen=True)
class Settings:
    api_url: str
    cache_path: Path
    http_timeout: float = 15.0
    page_size: int = 50
    refresh_seconds: int = 60

    @classmethod
    def from_environment(cls) -> "Settings":
        data_root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        timeout = float(os.getenv("WMS_HTTP_TIMEOUT_SECONDS", "15"))
        if not 1 <= timeout <= 120:
            raise ValueError("WMS_HTTP_TIMEOUT_SECONDS должен быть от 1 до 120.")
        refresh = int(os.getenv("WMS_REFRESH_SECONDS", "60"))
        if refresh < 15:
            raise ValueError("WMS_REFRESH_SECONDS должен быть не меньше 15.")
        return cls(
            api_url=normalize_origin(os.getenv("WMS_API_URL", "http://127.0.0.1:8000")),
            cache_path=Path(os.getenv("WMS_CACHE_PATH", str(data_root / "pulsar/cache.db"))).expanduser(),
            http_timeout=timeout,
            refresh_seconds=refresh,
        )
