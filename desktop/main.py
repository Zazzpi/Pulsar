"""Run from the repository root with: python -m desktop.main."""

import logging
from logging.handlers import RotatingFileHandler
import sys

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox

from desktop.cache.sqlite_cache import SQLiteCache
from desktop.config import Settings, application_data_dir
from desktop.ui.clients_window import ClientsWindow
from desktop.ui.login_window import LoginWindow
from desktop.workers.request_worker import WorkerPool

STYLE = """
QWidget { font-size: 13px; }
QMainWindow, LoginWindow { background: #f4f6fa; }
QPushButton { padding: 7px 11px; }
QLineEdit, QComboBox, QDateEdit { padding: 6px; }
QListWidget, QTableWidget, QTextEdit { background: white; border: 1px solid #d7dde6; }
QListWidget::item { padding: 9px; }
QLabel#title { font-size: 21px; font-weight: bold; }
QWidget#metricCard { background: #e9eff7; border-radius: 5px; }
QLabel#metricValue { font-size: 24px; font-weight: bold; }
QLabel#warningBanner { background: #fff1c7; color: #543c00; padding: 10px; }
QLabel#resourceStatus { color: #475569; }
"""


def configure_appearance(app):
    # Fixed light surfaces need a matching palette even on a dark KDE desktop.
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#f4f6fa", QPalette.ColorRole.WindowText: "#172033",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.AlternateBase: "#edf2f8",
        QPalette.ColorRole.Text: "#172033", QPalette.ColorRole.Button: "#e9eff7",
        QPalette.ColorRole.ButtonText: "#172033", QPalette.ColorRole.Highlight: "#2563eb",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#172033", QPalette.ColorRole.PlaceholderText: "#64748b",
    }.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#7a8494"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


def configure_logging():
    """Windowed EXEs have no console; keep a bounded log in the user profile."""
    handlers = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    try:
        log_dir = application_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_dir / "pulsar.log", maxBytes=1_000_000,
                                           backupCount=2, encoding="utf-8"))
    except OSError:
        pass  # A logging failure must not prevent the GUI from opening.
    logging.basicConfig(level=logging.INFO, handlers=handlers or [logging.NullHandler()],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def report_unhandled_error(error_type, _error, _traceback):
    # Exception text may contain an HTTP payload; do not write it to logs.
    logging.getLogger(__name__).error("Unhandled desktop error (%s)", error_type.__name__)
    QMessageBox.critical(None, "Pulsar", "Не удалось выполнить действие. Повторите его или перезапустите приложение.")


class ApplicationController(QObject):
    def __init__(self, app, settings, cache):
        super().__init__(app)
        self.app, self.settings, self.cache = app, settings, cache
        self.workers = WorkerPool(self)
        self.window = None

    def show_login(self, message=""):
        old = self.window
        self.window = LoginWindow(self.settings, self.cache, self.workers)
        self.window.authenticated.connect(self.show_clients)
        if message:
            self.window.status.setText(message)
        self.window.show()
        if old:
            old.close()
            old.deleteLater()

    def show_clients(self, api, user, offline):
        old = self.window
        self.window = ClientsWindow(self.settings, api, user, self.cache, self.workers, offline)
        self.window.signed_out.connect(self.show_login)
        self.window.show()
        if old:
            old.close()
            old.deleteLater()


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Pulsar")
    configure_appearance(app)
    sys.excepthook = report_unhandled_error
    try:
        settings = Settings.from_environment()
        cache = SQLiteCache(settings.cache_path)
    except Exception as exc:
        logging.getLogger(__name__).error("Desktop initialization failed (%s)", type(exc).__name__)
        QMessageBox.critical(None, "Pulsar", f"Не удалось открыть настройки или локальный кэш: {exc}")
        return 1
    controller = ApplicationController(app, settings, cache)
    controller.show_login()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
