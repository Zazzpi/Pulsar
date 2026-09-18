"""Build verification of the frozen executable without a WMS connection."""
import json
from pathlib import Path
import sys
import tempfile

import certifi
import requests
from PyQt6.QtCore import QTimer, qVersion
from PyQt6.QtWidgets import QApplication

from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings, application_data_dir
from desktop.demo import DemoApiClient
from desktop.main import ApplicationController


def check_bundle(report_path: str) -> int:
    report = Path(report_path)
    try:
        assert getattr(sys, "frozen", False), "Expected the packaged executable"
        bundle = Path(sys._MEIPASS)
        assert Path(certifi.where()).is_file(), "Missing HTTPS certificate bundle"
        assert Path(requests.__file__).is_relative_to(bundle)
        app = QApplication([])
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
            timer = QTimer()
            timer.timeout.connect(lambda: app.quit() if controller.window.details.panels[0].loaded else None)
            timer.start(50)
            QTimer.singleShot(10000, app.quit)
            app.exec()
            timer.stop()
            assert controller.window.details.panels[0].loaded, "Demo did not render"
            assert controller.window.details.panels[0].metrics["stock.available"].text() != "—"
            controller.window.close()
            controller.workers.pool.waitForDone(5000)
        report.write_text(json.dumps({
            "ok": True, "frozen": True, "platform": sys.platform, "qt": qVersion(),
            "data_directory": str(application_data_dir()),
            "checks": ["Qt login window", "local demo window", "SQLite", "bundled requests", "HTTPS CA bundle"],
        }, indent=2), encoding="utf-8")
        return 0
    except Exception as error:
        # This isolated check handles only synthetic demo data, never login secrets.
        report.write_text(json.dumps({"ok": False, "error": type(error).__name__,
                                      "detail": str(error)}), encoding="utf-8")
        return 1
