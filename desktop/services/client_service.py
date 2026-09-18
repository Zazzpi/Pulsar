import logging
import sqlite3
from datetime import datetime, timezone

from desktop.api.client import ApiClient, ApiError
from desktop.api.contracts import validate_read_payload
from desktop.cache.sqlite_cache import SQLiteCache, user_namespace
from desktop.models.dto import CachedResponse

logger = logging.getLogger(__name__)


class ClientService:
    def __init__(self, api: ApiClient, cache: SQLiteCache, user: dict, offline: bool = False):
        self.api, self.cache, self.user, self.offline = api, cache, user, offline
        self.namespace = user_namespace(api.origin, user)

    def cached(self, path: str, params: dict | None = None) -> CachedResponse | None:
        try:
            response = self.cache.get(self.namespace, path, params)
            if response is not None:
                validate_read_payload(path, response.payload)
            return response
        except (sqlite3.Error, OSError, ApiError):
            logger.warning("Could not read local cache")
            return None

    def fetch(self, path: str, params: dict | None = None) -> CachedResponse:
        if self.offline:
            raise ApiError("Открыты сохранённые данные. Войдите для обновления.")
        payload = self.api.request("GET", path, params=params)
        validate_read_payload(path, payload)
        updated_at = datetime.now(timezone.utc).isoformat()
        try:
            updated_at = self.cache.put(self.namespace, path, payload, params)
        except (sqlite3.Error, OSError):
            logger.warning("Fresh data could not be persisted in SQLite")
        return CachedResponse(payload, updated_at)

    def mutate(self, method: str, path: str, data: dict | None = None):
        if self.offline:
            raise ApiError("В режиме сохранённых данных изменения недоступны.")
        return self.api.request(method, path, data=data)

    def invalidate(self, path: str):
        try:
            self.cache.invalidate(self.namespace, path)
        except (sqlite3.Error, OSError):
            logger.warning("Could not invalidate local cache")
