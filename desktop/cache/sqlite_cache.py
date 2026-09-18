"""Response-only cache. A connection per operation permits Qt worker threads."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desktop.config import normalize_origin
from desktop.models.dto import CachedResponse

logger = logging.getLogger(__name__)


def user_namespace(origin: str, user: dict) -> str:
    return json.dumps([normalize_origin(origin), str(user["id"]), user["username"]], ensure_ascii=False)


def response_key(path: str, params: dict | None = None) -> str:
    if not path.startswith("/api/") or path.startswith("/api/auth/"):
        raise ValueError("В кэше разрешены только ответы API с данными.")
    return json.dumps([path, params or {}], sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class SQLiteCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS responses (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, cache_key)
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    namespace TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                );
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        except sqlite3.Error:
            logger.exception("SQLite operation failed")
            raise
        finally:
            connection.close()

    def get(self, namespace: str, path: str, params: dict | None = None) -> CachedResponse | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT payload_json, updated_at FROM responses WHERE namespace = ? AND cache_key = ?",
                (namespace, response_key(path, params)),
            ).fetchone()
        if not row:
            return None
        try:
            return CachedResponse(json.loads(row[0]), row[1])
        except (ValueError, TypeError, RecursionError):
            logger.warning("Discarded corrupt SQLite JSON")
            return None

    def put(self, namespace: str, path: str, payload: Any, params: dict | None = None) -> str:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO responses(namespace, cache_key, payload_json, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(namespace, cache_key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (namespace, response_key(path, params), json.dumps(payload, ensure_ascii=False), updated_at),
            )
        return updated_at

    def invalidate(self, namespace: str, path: str) -> None:
        """Remove all cached pages for a changed resource, within this user only."""
        with self.connection() as connection:
            rows = connection.execute("SELECT cache_key FROM responses WHERE namespace = ?", (namespace,)).fetchall()
            keys = []
            for row in rows:
                try:
                    key = json.loads(row[0])
                    matches = isinstance(key, list) and len(key) == 2 and key[0] == path
                except (ValueError, TypeError, RecursionError):
                    matches = True  # A corrupt cache entry is safe to discard.
                if matches:
                    keys.append((namespace, row[0]))
            connection.executemany("DELETE FROM responses WHERE namespace = ? AND cache_key = ?", keys)

    def remember_profile(self, origin: str, user: dict) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO profiles(namespace, origin, user_id, username, last_used_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(namespace) DO UPDATE SET last_used_at=excluded.last_used_at",
                (user_namespace(origin, user), normalize_origin(origin), str(user["id"]), user["username"], datetime.now(timezone.utc).isoformat()),
            )

    def last_profile(self) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT origin, user_id, username FROM profiles p "
                "WHERE EXISTS (SELECT 1 FROM responses r WHERE r.namespace=p.namespace) "
                "ORDER BY last_used_at DESC LIMIT 1"
            ).fetchone()
        return {"origin": row[0], "user": {"id": row[1], "username": row[2]}} if row else None
