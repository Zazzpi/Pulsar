from datetime import datetime, timedelta
import sys

import pytest
import requests
from PyQt6.QtTest import QTest

from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings, application_data_dir
from desktop.demo import DemoApiClient
from desktop.main import ApplicationController
from desktop.ui.clients_window import ClientsWindow


def test_windows_data_is_in_user_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert application_data_dir() == tmp_path / "Pulsar"


def test_frozen_first_run_does_not_assume_local_server(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("WMS_API_URL", raising=False)
    assert Settings.from_environment().api_url == ""
    monkeypatch.setenv("WMS_API_URL", "https://sales.example.org")
    assert Settings.from_environment().api_url == "https://sales.example.org"


def test_demo_watches_and_notes_persist_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: pytest.fail("Demo attempted HTTP"))
    demo = DemoApiClient(tmp_path / "demo.sqlite3")
    watch = demo.request("POST", "/api/watches/", data={"wms_client_id": 1})
    assert datetime.fromisoformat(watch["ends_at"]) - datetime.fromisoformat(watch["started_at"]) == timedelta(days=90)
    assert demo.request("POST", "/api/watches/", data={"wms_client_id": 1}) == watch
    demo.request("POST", "/api/clients/1/notes/", data={"body": "Позвонить клиенту"})
    reopened = DemoApiClient(tmp_path / "demo.sqlite3")
    assert reopened.request("GET", "/api/watches/")["results"][0] == watch
    assert reopened.request("GET", "/api/clients/1/notes/")["results"][0]["body"] == "Позвонить клиенту"
    assert reopened.request("GET", "/api/clients/2/notes/")["results"] == []
    reopened.request("DELETE", "/api/watches/1/")
    assert reopened.request("GET", "/api/watches/")["results"] == []


def test_demo_search_pagination_and_dates(tmp_path):
    demo = DemoApiClient(tmp_path / "demo.sqlite3")
    assert demo.request("GET", "/api/clients/", params={"q": "ром"})["results"][0]["id"] == 1
    first = demo.request("GET", "/api/clients/1/movements/", params={"page": 1, "page_size": 50})
    second = demo.request("GET", "/api/clients/1/movements/", params={"page": 2, "page_size": 50})
    assert len(first["results"]) == 50 and first["has_next"]
    assert len(second["results"]) == 22 and not second["has_next"]
    assert not demo.request("GET", "/api/clients/1/orders/", params={"from": "2000-01-01", "to": "2000-02-01"})["results"]


def test_demo_releases_database_handles_on_windows(tmp_path):
    path = tmp_path / "demo.sqlite3"
    demo = DemoApiClient(path)
    demo.request("POST", "/api/watches/", data={"wms_client_id": 1})
    demo.request("GET", "/api/watches/")
    # Windows refuses this if sqlite connections still hold the file open.
    renamed = path.with_suffix(".moved")
    path.rename(renamed)
    renamed.unlink()


def test_demo_button_opens_populated_gui_without_server(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "request", lambda *a, **kw: pytest.fail("Demo attempted HTTP"))
    settings = Settings("", tmp_path / "cache.db")
    controller = ApplicationController(qapp, settings, SQLiteCache(settings.cache_path))
    controller.show_login()
    assert controller.window.api_url.text() == ""
    controller.window.demo_button.click()
    assert isinstance(controller.window, ClientsWindow)
    window = controller.window
    try:
        for _ in range(100):
            if window.details.panels[0].loaded:
                break
            QTest.qWait(20)
        assert window.clients.count() == 3
        assert window.details.panels[0].loaded
        assert "Демо" in window.banner.text()
        assert window.details.watch_button.isEnabled()
    finally:
        window.close()
        controller.workers.pool.waitForDone(10000)
