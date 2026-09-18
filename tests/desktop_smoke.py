"""Real desktop HTTP worker + persisted/offline cache check against local DEMO.

QT_QPA_PLATFORM=offscreen python -m tests.desktop_smoke
"""
from __future__ import annotations

from pathlib import Path
import tempfile

from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from desktop.api.client import ApiClient, ApiError
from desktop.cache.sqlite_cache import SQLiteCache
from desktop.services.client_service import ClientService
from desktop.workers.request_worker import WorkerPool


def main() -> None:
    app = QApplication([])
    workers = WorkerPool()
    env = dict(
        line.split("=", 1)
        for line in Path(".env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    api = ApiClient("http://127.0.0.1:8000", timeout=5)

    def run(function):
        loop = QEventLoop()
        result, errors = [], []

        def in_worker():
            assert QThread.currentThread() != app.thread(), "Network call entered UI thread"
            return function()

        def success(value):
            assert QThread.currentThread() == app.thread()
            result.append(value)
            loop.quit()

        def failure(error):
            errors.append(error)
            loop.quit()

        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(15000)
        workers.submit(in_worker, success, failure)
        loop.exec()
        timeout.stop()
        if errors:
            raise errors[0]
        assert result, "Worker did not finish"
        return result[0]

    user = run(lambda: api.login(env["DEMO_USERNAME"], env["DEMO_PASSWORD"]))
    with tempfile.TemporaryDirectory(prefix="pulsar-cache-") as directory:
        path = Path(directory) / "cache.db"
        cache = SQLiteCache(path)
        cache.remember_profile(api.origin, user)
        service = ClientService(api, cache, user)
        params = {"page": 1, "page_size": 50}
        clients = run(lambda: service.fetch("/api/clients/", params))
        cid = clients.payload["results"][0]["id"]
        route = f"/api/clients/{cid}/summary/"
        summary = run(lambda: service.fetch(route, {}))
        run(lambda: service.fetch("/api/watches/", params))
        restored = SQLiteCache(path)
        assert restored.last_profile()["user"]["username"] == user["username"]
        offline = ClientService(ApiClient(api.origin), restored, user, offline=True)
        assert offline.cached(route, {}).payload == summary.payload
        assert offline.cached("/api/clients/", params).payload == clients.payload
        another = ClientService(api, restored, {"id": "other", "username": user["username"]}, offline=True)
        assert another.cached(route, {}) is None
        try:
            offline.mutate("POST", "/api/watches/", {"wms_client_id": cid})
        except ApiError:
            pass
        else:
            raise AssertionError("Offline mutation allowed")
        print("OK Qt HTTP workers, UI-thread callbacks, SQLite reopening, offline reads, user isolation")
    run(api.logout)
    workers.pool.waitForDone(10000)
    app.processEvents()


if __name__ == "__main__":
    main()
