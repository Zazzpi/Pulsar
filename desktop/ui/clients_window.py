from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from desktop.api.client import ApiError
from desktop.models.dto import display_time, watch_caption
from desktop.services.client_service import ClientService
from desktop.services.sync_service import SyncService
from desktop.ui.client_details import ClientDetails
from desktop.ui.resource_panels import plain_label


class ClientsWindow(QMainWindow):
    signed_out = pyqtSignal(str)

    def __init__(self, settings, api, user, cache, workers, offline=False):
        super().__init__()
        self.settings, self.workers = settings, workers
        self.service = ClientService(api, cache, user, offline)
        self.sync = SyncService(self.service, workers)
        self.page, self.has_next, self.revision = 1, False, 0
        self.disposed, self.busy, self.loaded = False, False, False
        self.query = ""
        self.setWindowTitle("Pulsar · 90-дневный мониторинг клиентов")
        self.resize(1250, 800)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        header = QHBoxLayout()
        demo = getattr(api, "demo", False)
        header.addWidget(plain_label("Демонстрация · данные на этом компьютере" if demo else f"{user['username']} · {api.origin}"))
        header.addStretch()
        self.logout_button = QPushButton("Войти" if offline else "Выйти")
        self.logout_button.clicked.connect(self.logout)
        header.addWidget(self.logout_button)
        layout.addLayout(header)
        self.banner = plain_label()
        self.banner.setObjectName("warningBanner")
        self.banner.setVisible(offline or demo)
        self.banner.setText("Демо: тестовые данные. Наблюдения и заметки сохраняются только на этом компьютере."
                            if demo else "Сохранённые данные могут быть устаревшими. Войдите для обновления и изменений.")
        layout.addWidget(self.banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setMaxLength(200)
        self.search.setPlaceholderText("Название или ИНН")
        self.search.returnPressed.connect(self.search_clients)
        search_button = QPushButton("Найти")
        search_button.clicked.connect(self.search_clients)
        search_row.addWidget(self.search)
        search_row.addWidget(search_button)
        side.addLayout(search_row)
        self.mode = QComboBox()
        self.mode.addItems(["Мои клиенты", "Все клиенты"])
        self.mode.currentIndexChanged.connect(self.mode_changed)
        side.addWidget(self.mode)
        self.list_status = plain_label()
        side.addWidget(self.list_status)
        self.clients = QListWidget()
        self.clients.setWordWrap(True)
        self.clients.currentItemChanged.connect(self.select_client)
        side.addWidget(self.clients)
        paging = QHBoxLayout()
        self.previous = QPushButton("←")
        self.previous.setToolTip("Предыдущая страница")
        self.next = QPushButton("→")
        self.next.setToolTip("Следующая страница")
        self.previous.clicked.connect(lambda: self.change_page(-1))
        self.next.clicked.connect(lambda: self.change_page(1))
        self.page_label = plain_label("Страница 1")
        paging.addWidget(self.previous)
        paging.addWidget(self.page_label)
        paging.addWidget(self.next)
        side.addLayout(paging)
        refresh = QPushButton("Обновить список")
        refresh.clicked.connect(self.load_list)
        refresh.setEnabled(not offline)
        self.list_refresh = refresh
        side.addWidget(refresh)
        splitter.addWidget(sidebar)
        self.details = ClientDetails(self.sync, settings.page_size, settings.refresh_seconds)
        self.details.watches_changed.connect(self.watches_changed)
        self.details.api_error.connect(self.handle_error)
        splitter.addWidget(self.details)
        splitter.setSizes([320, 930])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        layout.addWidget(splitter)
        self.update_pages()
        if demo:
            self.mode.setCurrentIndex(1)
        else:
            self.load_list()

    def update_pages(self):
        self.previous.setEnabled(self.page > 1)
        self.next.setEnabled(self.has_next)
        self.page_label.setText(f"Страница {self.page}")

    def mode_changed(self):
        if self.mode.currentIndex() == 0:
            self.query = ""
        else:
            self.query = self.search.text().strip()
        self.page = 1
        self.reset_list()
        self.load_list()

    def search_clients(self):
        self.query = self.search.text().strip()
        if self.mode.currentIndex() != 1:
            self.mode.setCurrentIndex(1)
        else:
            self.page = 1
            self.reset_list()
            self.load_list()

    def change_page(self, delta):
        self.page = max(1, self.page + delta)
        self.reset_list()
        self.load_list()

    def reset_list(self):
        self.revision += 1
        self.busy, self.loaded, self.has_next = False, False, False
        self.clients.clear()
        self.details.clear_client()
        self.update_pages()

    def load_list(self):
        if self.busy or self.disposed:
            return
        self.revision += 1
        revision = self.revision
        watches = self.mode.currentIndex() == 0
        path = "/api/watches/" if watches else "/api/clients/"
        params = {"page": self.page, "page_size": self.settings.page_size}
        if not watches:
            params["q"] = self.query
        self.busy = True

        def active():
            return not self.disposed and revision == self.revision

        def show(response, stale):
            if not active():
                return
            self.loaded = True
            self.busy = stale and not self.service.offline
            selected_id = self.details.client["id"] if self.details.client else None
            self.clients.blockSignals(True)
            self.clients.clear()
            selected_item = None
            for row in response.payload.get("results", []):
                client = row.get("client") if watches else row
                if not client:
                    continue
                title = client.get("name", str(client["id"]))
                detail = watch_caption(row) if watches else f"ИНН: {client.get('inn') or '—'}"
                item = QListWidgetItem(f"{title}\n{detail}")
                item.setData(Qt.ItemDataRole.UserRole, {"client": client, "watch": row if watches else None})
                self.clients.addItem(item)
                if client["id"] == selected_id:
                    selected_item = item
            if selected_item:
                self.clients.setCurrentItem(selected_item)
            else:
                self.details.clear_client()
            self.clients.blockSignals(False)
            self.has_next = bool(response.payload.get("has_next"))
            self.update_pages()
            empty = "Клиенты не найдены. " if not self.clients.count() else ""
            stale_text = "Данные могут быть устаревшими. " if stale else ""
            self.list_status.setText(f"{empty}{stale_text}Обновлено: {display_time(response.updated_at)}")
            if self.clients.count() and self.details.client is None:
                self.clients.setCurrentRow(0)

        def loading(has_cache):
            if active():
                self.list_status.setText(self.list_status.text() + " · Обновление…" if has_cache else "Загрузка…")

        def failed(error):
            if not active():
                return
            self.busy = False
            prefix = "Данные могут быть устаревшими. " if self.loaded else ""
            old = self.list_status.text().replace(" · Обновление…", "") if self.loaded else ""
            self.list_status.setText(prefix + str(error) + (f"\n{old}" if old else ""))
            self.handle_error(error)

        self.sync.load(path, params, show, failed, loading)

    def select_client(self, item, _previous):
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            self.details.set_client(data["client"], data["watch"])

    def watches_changed(self):
        if self.mode.currentIndex() == 0:
            self.revision += 1
            self.busy = False
            self.load_list()

    def handle_error(self, error):
        if isinstance(error, ApiError) and error.status in {401, 403} and not self.service.offline:
            self.service.offline = True
            self.service.api.token = None
            self.banner.setText("Сессия недоступна. Сохранённые данные могут быть устаревшими. Войдите снова.")
            self.banner.show()
            self.logout_button.setText("Войти")
            self.list_refresh.setEnabled(False)
            self.details.update_access()

    def logout(self):
        if self.service.offline:
            self.signed_out.emit("")
            return
        self.logout_button.setEnabled(False)
        self.details.timer.stop()

        def success(_result):
            if not self.disposed:
                self.signed_out.emit("")

        def failed(_error):
            if not self.disposed:
                self.signed_out.emit("Локальный выход выполнен. Сервер не подтвердил завершение сессии; токен будет действовать до истечения срока.")

        self.workers.submit(self.service.api.logout, success, failed)

    def dispose(self):
        self.disposed = True
        self.revision += 1
        self.details.dispose()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
