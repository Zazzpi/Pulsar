import logging
import sqlite3

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from desktop.api.client import ApiClient
from desktop.ui.resource_panels import plain_label

logger = logging.getLogger(__name__)


class LoginWindow(QWidget):
    authenticated = pyqtSignal(object, object, bool)

    def __init__(self, settings, cache, workers):
        super().__init__()
        self.settings, self.cache, self.workers = settings, cache, workers
        self.disposed = False
        self.setWindowTitle("Pulsar · вход")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        title = QLabel("Pulsar · мониторинг клиентов")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        self.api_url = QLineEdit(settings.api_url)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.login)
        form.addRow("Адрес сервера", self.api_url)
        form.addRow("Логин", self.username)
        form.addRow("Пароль", self.password)
        layout.addLayout(form)
        self.status = plain_label("Для удалённого сервера используйте HTTPS.")
        layout.addWidget(self.status)
        self.login_button = QPushButton("Войти")
        self.login_button.clicked.connect(self.login)
        layout.addWidget(self.login_button)
        self.offline_button = QPushButton("Открыть сохранённые данные")
        self.offline_button.clicked.connect(self.open_offline)
        layout.addWidget(self.offline_button)
        try:
            self.profile = cache.last_profile()
        except (sqlite3.Error, OSError):
            self.profile = None
        self.offline_button.setEnabled(self.profile is not None)
        if self.profile:
            self.api_url.setText(self.profile["origin"])
            self.username.setText(self.profile["user"]["username"])
            layout.addWidget(plain_label(
                f"Локальная копия: {self.profile['user']['username']} · {self.profile['origin']}\n"
                "Просмотр без соединения не проверяет пароль. Доступ защищается учётной записью компьютера."
            ))

    def set_busy(self, busy):
        for widget in (self.login_button, self.username, self.password, self.api_url):
            widget.setEnabled(not busy)
        self.offline_button.setEnabled(not busy and self.profile is not None)

    def login(self):
        if not self.login_button.isEnabled():
            return
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.status.setText("Введите логин и пароль.")
            return
        try:
            api = ApiClient(self.api_url.text(), timeout=self.settings.http_timeout)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.set_busy(True)
        self.status.setText("Вход…")
        self.password.clear()

        def authenticate():
            user = api.login(username, password)
            try:
                self.cache.remember_profile(api.origin, user)
            except (sqlite3.Error, OSError):
                logger.warning("Could not save last user profile")
            return user

        def success(user):
            if not self.disposed:
                self.set_busy(False)
                self.authenticated.emit(api, user, False)

        def failed(error):
            if not self.disposed:
                self.set_busy(False)
                self.status.setText(str(error))

        self.workers.submit(authenticate, success, failed)

    def open_offline(self):
        if self.profile:
            api = ApiClient(self.profile["origin"], timeout=self.settings.http_timeout)
            self.authenticated.emit(api, self.profile["user"], True)

    def closeEvent(self, event):
        self.disposed = True
        super().closeEvent(event)
