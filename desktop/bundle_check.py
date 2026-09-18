"""Build verification of the frozen executable without a WMS connection."""
import json
from pathlib import Path
import sys
import tempfile
import time

import certifi
import requests
from PyQt6.QtCore import qVersion
from PyQt6.QtWidgets import QApplication

from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings, application_data_dir
from desktop.demo import DemoApiClient
from desktop.main import ApplicationController, configure_appearance


def check_bundle(report_path: str) -> int:
    report = Path(report_path)
    try:
        assert getattr(sys, "frozen", False), "Expected the packaged executable"
        bundle = Path(sys._MEIPASS)
        assert Path(certifi.where()).is_file(), "Missing HTTPS certificate bundle"
        assert Path(requests.__file__).is_relative_to(bundle)
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        configure_appearance(app)

        def wait(predicate):
            deadline = time.monotonic() + 10
            while not predicate():
                if time.monotonic() > deadline:
                    raise RuntimeError("Demo action timed out")
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()
        with tempfile.TemporaryDirectory(prefix="pulsar-bundle-") as directory:
            config = Settings("", Path(directory) / "cache.db")
            cache = SQLiteCache(config.cache_path)
            cache.put("build-check", "/api/clients/", {"results": []})
            assert cache.get("build-check", "/api/clients/").payload == {"results": []}
            controller = ApplicationController(app, config, cache)
            controller.show_login()
            assert controller.window.isVisible()
            assert controller.window.api_url.text() == ""
            demo = DemoApiClient(Path(directory) / "demo.sqlite3")
            assert demo.request("GET", "/api/clients/")["results"]
            assert demo.request("GET", "/api/clients/1/summary/")["stock"]["available"] == 160
            controller.window.demo_button.click()
            window = controller.window
            details = window.details
            wait(lambda: details.panels[0].loaded and not details.watch_busy)
            assert details.panels[0].metrics["stock.available"].text() == "160"
            window.grab().save(str(report.with_suffix(".png")))
            for index, panel in enumerate(details.panels):
                details.tabs.setCurrentIndex(index)
                wait(lambda: panel.loaded and not panel.busy)
            details.tabs.setCurrentIndex(5)
            movements = details.panels[5]
            assert movements.table.rowCount() == 50
            movements.next.click()
            wait(lambda: movements.loaded and not movements.busy)
            assert movements.table.rowCount() == 22
            details.watch_button.click()
            wait(lambda: details.watch and details.watch.get("is_active") and not details.watch_busy)
            details.tabs.setCurrentIndex(6)
            notes = details.panels[6]
            notes.editor.setPlainText("Проверка автономной сборки")
            notes.save_button.click()
            wait(lambda: not notes.saving and notes.loaded and not notes.busy)
            assert "Проверка автономной сборки" in notes.notes.item(0).text()
            reopened = DemoApiClient(Path(directory) / "demo.sqlite3")
            assert reopened.request("GET", "/api/clients/1/notes/")["results"][0]["body"] == "Проверка автономной сборки"
            assert reopened.request("GET", "/api/watches/")["results"]
            window.search.setText("Альфа")
            window.search_clients()
            wait(lambda: window.loaded and not window.busy)
            assert details.client["id"] == 2
            window.search.setText("Несуществующий клиент")
            window.search_clients()
            wait(lambda: window.loaded and not window.busy)
            assert details.client is None and not details.watch_button.isEnabled()
            controller.window.close()
            controller.workers.pool.waitForDone(5000)
        report.write_text(json.dumps({
            "ok": True, "frozen": True, "platform": sys.platform, "qt": qVersion(),
            "data_directory": str(application_data_dir()),
            "checks": ["Qt login window", "seven demo tabs", "movement pagination", "watch creation",
                       "note persistence", "client search and empty results", "SQLite", "bundled requests", "HTTPS CA bundle"],
        }, indent=2), encoding="utf-8")
        return 0
    except Exception as error:
        # This isolated check handles only synthetic demo data, never login secrets.
        report.write_text(json.dumps({"ok": False, "error": type(error).__name__,
                                      "detail": str(error)}), encoding="utf-8")
        return 1
