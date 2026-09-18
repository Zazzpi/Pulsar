from concurrent.futures import ThreadPoolExecutor

import pytest

from desktop.cache.sqlite_cache import SQLiteCache, user_namespace


def test_cache_isolated_by_origin_user_and_request_params(tmp_path):
    cache = SQLiteCache(tmp_path / "cache.db")
    first_user = {"id": 1, "username": "alice"}
    namespace = user_namespace("https://warehouse.test", first_user)
    path = "/api/clients/3/movements/"
    params = {"page": 1, "from": "2026-08-01", "to": "2026-09-01"}
    cache.put(namespace, path, {"results": [{"quantity": "4"}]}, params)
    assert cache.get(namespace, path, params).payload["results"][0]["quantity"] == "4"
    assert cache.get(namespace, path, {**params, "page": 2}) is None
    assert cache.get(namespace, path, {**params, "from": "2026-08-02"}) is None
    for other in (
        user_namespace("https://other.test", first_user),
        user_namespace("https://warehouse.test", {"id": 2, "username": "alice"}),
        user_namespace("https://warehouse.test", {"id": 1, "username": "bob"}),
    ):
        assert cache.get(other, path, params) is None


def test_profile_reopening_and_no_auth_storage(tmp_path):
    path = tmp_path / "cache.db"
    cache = SQLiteCache(path)
    user = {"id": 1, "username": "alice", "token": "private-token", "password": "private-password"}
    origin = "https://warehouse.test"
    namespace = user_namespace(origin, user)
    cache.remember_profile(origin, user)
    assert cache.last_profile() is None
    cache.put(namespace, "/api/watches/", {"results": []})
    reopened = SQLiteCache(path)
    assert reopened.last_profile() == {"origin": origin, "user": {"id": "1", "username": "alice"}}
    assert b"private-token" not in path.read_bytes()
    assert b"private-password" not in path.read_bytes()
    with pytest.raises(ValueError):
        cache.put(namespace, "/api/auth/login/", {"token": "secret"})


def test_parallel_sqlite_writers_and_scoped_invalidation(tmp_path):
    cache = SQLiteCache(tmp_path / "cache.db")
    path = "/api/watches/"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda number: cache.put("one", path, {"value": number}, {"page": number}), range(12)))
    cache.put("two", path, {"value": "untouched"})
    cache.put("one", "/api/clients/", {"results": []})
    cache.invalidate("one", path)
    assert all(cache.get("one", path, {"page": index}) is None for index in range(12))
    assert cache.get("two", path).payload == {"value": "untouched"}
    assert cache.get("one", "/api/clients/").payload == {"results": []}
