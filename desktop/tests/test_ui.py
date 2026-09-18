from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from desktop.api.client import ApiClient, ApiError
from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings
from desktop.models.dto import CachedResponse
from desktop.services.client_service import ClientService
from desktop.services.sync_service import SyncService
from desktop.ui.client_details import ClientDetails
from desktop.ui.clients_window import ClientsWindow
from desktop.ui.login_window import LoginWindow
from desktop.ui.resource_panels import TablePanel


class QueuedWorkers:
    def __init__(self):
        self.jobs = []

    def submit(self, function, success, failure):
        self.jobs.append((function, success, failure))


@pytest.fixture
def context(tmp_path, qapp):
    cache = SQLiteCache(tmp_path / "cache.db")
    api = ApiClient("https://warehouse.test", "memory-token")
    user = {"id": 1, "username": "alice"}
    workers = QueuedWorkers()
    service = ClientService(api, cache, user)
    return cache, api, user, workers, service, SyncService(service, workers)


def fresh(payload):
    return CachedResponse(payload, "2026-09-18T10:00:00+00:00")


def test_lazy_tabs_ignore_response_for_previous_client(context):
    _cache, _api, _user, workers, _service, sync = context
    details = ClientDetails(sync)
    details.set_client({"id": 1, "name": "Первый"})
    assert len(workers.jobs) == 2  # summary plus current client's watch, no detail preloads
    old_summary = workers.jobs[0]
    details.set_client({"id": 2, "name": "Второй"})
    new_summary = workers.jobs[2]
    old_summary[1](fresh({"stock": {"total": "111"}}))
    assert details.panels[0].metrics["stock.total"].text() == "—"
    new_summary[1](fresh({"stock": {"total": "222"}}))
    assert details.panels[0].metrics["stock.total"].text() == "222"
    assert len(workers.jobs) == 4
    details.tabs.setCurrentIndex(5)
    assert len(workers.jobs) == 5
    assert details.panels[5].client_id == 2
    details.dispose()
    details.close()


def test_cached_render_precedes_refresh_and_failure_preserves_data(context):
    cache, _api, _user, workers, service, sync = context
    panel = TablePanel(sync, "stock")
    panel.set_client(1)
    cache.put(service.namespace, panel.path, {"results": [{"quantity": "123"}], "has_next": False}, panel.params())
    panel.refresh()
    assert panel.table.item(0, 0).text() == "123"
    assert "устаревшими" in panel.status.text()
    assert len(workers.jobs) == 1
    workers.jobs[0][2](ApiError("Нет соединения"))
    assert panel.table.item(0, 0).text() == "123"
    assert "устаревшими" in panel.status.text()
    assert "Обновлено" in panel.status.text()
    panel.close()


def test_offline_never_sends_network_or_mutates(context):
    cache, api, user, workers, service, sync = context
    api.request = Mock()
    service.offline = True
    panel = TablePanel(sync, "stock")
    panel.set_client(1)
    cache.put(service.namespace, panel.path, {"results": [{"quantity": "7"}]}, panel.params())
    panel.refresh()
    assert panel.table.item(0, 0).text() == "7"
    assert workers.jobs == []
    with pytest.raises(ApiError):
        service.fetch("/api/clients/")
    with pytest.raises(ApiError):
        service.mutate("POST", "/api/watches/", {"wms_client_id": 1})
    api.request.assert_not_called()
    details = ClientDetails(sync)
    details.set_client({"id": 1, "name": "Первый"})
    assert not details.watch_button.isEnabled()
    assert not details.panels[-1].save_button.isEnabled()
    assert not details.timer.isActive()
    details.dispose()
    details.close()
    panel.close()


def test_date_filter_includes_today_and_limits_ninety_days(context):
    *_rest, sync = context
    panel = TablePanel(sync, "movements")
    selected = panel.params()
    assert date.fromisoformat(selected["to"]) == date.today() + timedelta(days=1)
    assert (date.fromisoformat(selected["to"]) - date.fromisoformat(selected["from"])).days == 90
    panel.date_from.setDate(panel.date_to.date().addDays(-90))
    panel.apply_dates()
    assert "не более 90" in panel.status.text()
    assert panel.params() == selected
    panel.close()


def test_search_response_race_and_expired_session(context, tmp_path):
    cache, api, user, workers, _service, _sync = context
    settings = Settings(api.origin, tmp_path / "cache.db")
    window = ClientsWindow(settings, api, user, cache, workers)
    initial = workers.jobs[0]
    window.search.setText("Второй")
    window.search_clients()
    searching = workers.jobs[1]
    initial[1](fresh({"results": [{"client": {"id": 1, "name": "Первый"}}]}))
    assert window.clients.count() == 0
    searching[1](fresh({"results": [{"id": 2, "name": "Второй", "is_active": True}]}))
    assert window.clients.count() == 1
    assert window.details.client["id"] == 2
    window.handle_error(ApiError("expired", 401))
    assert window.service.offline
    assert api.token is None
    assert not window.details.watch_button.isEnabled()
    assert not window.details.panels[-1].save_button.isEnabled()
    window.close()


def test_login_window_and_reopening_offline_profile(context, tmp_path):
    cache, api, user, workers, service, _sync = context
    cache.remember_profile(api.origin, user)
    cache.put(service.namespace, "/api/watches/", {"results": []})
    window = LoginWindow(Settings(api.origin, tmp_path / "cache.db"), cache, workers)
    received = []
    window.authenticated.connect(lambda *args: received.append(args))
    window.open_offline()
    offline_api, offline_user, offline = received[0]
    assert offline and offline_api.token is None
    assert offline_user["username"] == user["username"]
    assert workers.jobs == []
    window.close()
