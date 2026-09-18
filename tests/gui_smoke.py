"""Exercise the actual Qt windows against local Compose DEMO, including outage.

QT_QPA_PLATFORM=offscreen python -m tests.gui_smoke
Temporarily stops and restarts the local backend. Never targets production WMS.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings
from desktop.main import ApplicationController, STYLE
from desktop.ui.clients_window import ClientsWindow


def main():
    env = dict(
        line.split("=", 1) for line in Path(".env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert env.get("WMS_MODE") == "mock"
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)

    def wait(predicate, label, timeout=12):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, f"Timed out: {label}"
            QTest.qWait(20)
        app.processEvents()

    with tempfile.TemporaryDirectory(prefix="pulsar-gui-") as directory:
        settings = Settings("http://127.0.0.1:8000", Path(directory) / "cache.db", refresh_seconds=600)
        controller = ApplicationController(app, settings, SQLiteCache(settings.cache_path))
        controller.show_login()
        login = controller.window
        login.username.setText(env["DEMO_USERNAME"])
        login.password.setText(env["DEMO_PASSWORD"])
        login.login_button.click()
        wait(lambda: isinstance(controller.window, ClientsWindow), "login")
        window = controller.window
        wait(lambda: window.loaded and not window.busy, "my clients")
        window.mode.setCurrentIndex(1)
        wait(lambda: window.loaded and not window.busy, "client search")
        for index in range(window.clients.count()):
            if window.clients.item(index).data(Qt.ItemDataRole.UserRole)["client"]["id"] == 1:
                window.clients.setCurrentRow(index)
                break
        details = window.details
        wait(lambda: details.client and details.client["id"] == 1 and details.panels[0].loaded
             and not details.panels[0].busy and not details.watch_busy, "summary")
        assert details.panels[0].metrics["stock.available"].text() != "—"
        if not details.watch or not details.watch.get("is_active"):
            details.watch_button.click()
            wait(lambda: details.watch and details.watch.get("is_active") and not details.watch_busy
                 and not details.mutation_busy, "watch")
        for index, panel in enumerate(details.panels):
            details.tabs.setCurrentIndex(index)
            wait(lambda panel=panel: panel.loaded and not panel.busy, f"tab {panel.resource}")
        moves = details.panels[5]
        details.tabs.setCurrentIndex(5)
        assert moves.has_next
        moves.next.click()
        wait(lambda: moves.page == 2 and moves.loaded and not moves.busy, "movements page two")
        assert moves.table.rowCount() > 0
        notes = details.panels[6]
        details.tabs.setCurrentIndex(6)
        notes.editor.setPlainText("Проверка desktop: обсудить развитие клиента.")
        notes.save_button.click()
        wait(lambda: not notes.editor.toPlainText() and notes.loaded and not notes.busy, "save note")
        window.mode.setCurrentIndex(0)
        wait(lambda: window.loaded and not window.busy, "updated watches")
        details.tabs.setCurrentIndex(0)
        app.processEvents()
        window.grab().save("/tmp/pulsar-ui.png")
        print("OK Qt login, search, watch, all seven tabs, pagination, notes, screenshot")

        stopped = False
        try:
            subprocess.run(["docker", "compose", "stop", "backend"], check=True, capture_output=True)
            stopped = True
            details.refresh_button.click()
            wait(lambda: not details.panels[0].busy and not details.watch_busy, "backend outage")
            assert "устаревш" in details.panels[0].status.text()
            assert details.panels[0].metrics["stock.available"].text() != "—"
            window.close()
            controller.workers.pool.waitForDone(10000)
            reopened = ApplicationController(app, settings, SQLiteCache(settings.cache_path))
            reopened.show_login()
            assert reopened.window.offline_button.isEnabled()
            reopened.window.offline_button.click()
            saved = reopened.window
            assert isinstance(saved, ClientsWindow) and saved.service.offline
            assert saved.clients.count() > 0
            assert saved.details.panels[0].loaded
            assert not saved.details.watch_button.isEnabled()
            assert "устаревш" in saved.details.panels[0].status.text()
            saved.grab().save("/tmp/pulsar-offline.png")
            saved.close()
            reopened.workers.pool.waitForDone(10000)
            print("OK real backend outage, stale-data warning, persisted cache after GUI reopening")
        finally:
            if stopped:
                subprocess.run(["docker", "compose", "start", "backend"], check=True, capture_output=True)
            controller.workers.pool.waitForDone(10000)
            app.processEvents()


if __name__ == "__main__":
    main()
