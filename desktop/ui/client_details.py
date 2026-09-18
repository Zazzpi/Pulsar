from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QTabWidget, QVBoxLayout, QWidget

from desktop.models.dto import display_time, watch_caption
from desktop.services.watch_service import WatchService
from desktop.ui.resource_panels import NotesPanel, SummaryPanel, TablePanel, plain_label


class ClientDetails(QWidget):
    watches_changed = pyqtSignal()
    api_error = pyqtSignal(object)

    def __init__(self, sync, page_size=50, refresh_seconds=60):
        super().__init__()
        self.sync = sync
        self.watch_service = WatchService(sync.service)
        self.client = None
        self.watch = None
        self.revision = 0
        self.disposed = False
        self.watch_busy = False
        self.mutation_busy = False
        layout = QVBoxLayout(self)
        self.title = plain_label("Выберите клиента в списке")
        self.title.setObjectName("title")
        layout.addWidget(self.title)
        self.subtitle = plain_label()
        layout.addWidget(self.subtitle)
        self.watch_label = plain_label()
        layout.addWidget(self.watch_label)
        buttons = QHBoxLayout()
        self.watch_button = QPushButton("Отслеживать 90 дней")
        self.watch_button.clicked.connect(self.change_watch)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.watch_button)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.tabs = QTabWidget()
        self.panels = [
            SummaryPanel(sync), TablePanel(sync, "stock", page_size),
            TablePanel(sync, "orders", page_size), TablePanel(sync, "receivings", page_size),
            TablePanel(sync, "shipments", page_size), TablePanel(sync, "movements", page_size),
            NotesPanel(sync, page_size),
        ]
        titles = ("Обзор", "Остатки", "Заказы", "Приёмки", "Отгрузки", "Движения", "Заметки")
        for panel, title in zip(self.panels, titles):
            self.tabs.addTab(panel, title)
            panel.api_error.connect(self.api_error.emit)
        self.tabs.currentChanged.connect(self.tab_changed)
        layout.addWidget(self.tabs)
        self.timer = QTimer(self)
        self.timer.setInterval(refresh_seconds * 1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.update_access()

    def update_access(self):
        online = not self.sync.service.offline
        self.watch_button.setEnabled(online and self.client is not None and not self.watch_busy and not self.mutation_busy)
        self.refresh_button.setEnabled(online and self.client is not None)
        self.tabs.setEnabled(self.client is not None)
        for panel in self.panels:
            if isinstance(panel, NotesPanel):
                panel.update_access()
        if not online:
            self.timer.stop()

    def set_client(self, client: dict, watch: dict | None = None):
        if self.client and self.client["id"] == client["id"]:
            return
        self.revision += 1
        self.client, self.watch = client, watch
        self.watch_busy, self.mutation_busy = False, False
        self.title.setText(client.get("name", f"Клиент {client['id']}"))
        self.subtitle.setText(f"ИНН: {client.get('inn') or '—'} · " + ("Активен" if client.get("is_active", True) else "Неактивен"))
        for panel in self.panels:
            panel.set_client(client["id"])
        self.tabs.setCurrentIndex(0)
        self.panels[0].refresh()
        self.update_watch()
        self.update_access()
        self.load_watch()

    def update_watch(self):
        self.watch_label.setText(watch_caption(self.watch))
        active = self.watch and self.watch.get("is_active")
        self.watch_button.setText("Завершить наблюдение" if active else "Отслеживать 90 дней")

    def tab_changed(self, index):
        panel = self.panels[index]
        if not panel.loaded:
            panel.refresh()

    def refresh(self):
        if not self.client or self.sync.service.offline or self.disposed:
            return
        self.panels[self.tabs.currentIndex()].refresh()
        self.load_watch()

    def load_watch(self):
        if self.watch_busy or self.mutation_busy or self.client is None or self.disposed:
            return
        revision = self.revision
        client_id = self.client["id"]
        self.watch_busy = True
        self.update_access()

        def active():
            return not self.disposed and revision == self.revision and self.client["id"] == client_id

        def show(response, stale):
            if not active():
                return
            rows = response.payload.get("results", [])
            self.watch = next((row for row in rows if row.get("is_active")), rows[0] if rows else None)
            self.watch_busy = stale and not self.sync.service.offline
            self.update_watch()
            if stale:
                self.watch_label.setText(self.watch_label.text() + f" · Кэш от {display_time(response.updated_at)}")
            self.update_access()

        def failed(error):
            if active():
                self.watch_busy = False
                self.watch_label.setText(self.watch_label.text() + f"\nСтатус наблюдения не обновлён: {error}")
                self.update_access()
                self.api_error.emit(error)

        self.sync.load("/api/watches/", {"wms_client_id": client_id, "page": 1, "page_size": 50}, show, failed, lambda _cache: None)

    def change_watch(self):
        if not self.client or self.sync.service.offline or self.watch_busy or self.mutation_busy:
            return
        revision, client_id = self.revision, self.client["id"]
        watch = self.watch
        stopping = bool(watch and watch.get("is_active"))
        self.mutation_busy = True
        self.update_access()
        self.watch_label.setText("Сохранение наблюдения…")

        def action():
            if stopping:
                self.watch_service.stop(watch["id"])
                return None
            return self.watch_service.start(client_id)

        def success(result):
            if self.disposed:
                return
            self.watches_changed.emit()
            if revision != self.revision:
                return
            self.mutation_busy = False
            self.watch = result
            self.update_watch()
            self.update_access()
            self.load_watch()

        def failed(error):
            if not self.disposed and revision == self.revision:
                self.mutation_busy = False
                self.update_access()
                self.watch_label.setText(f"Наблюдение не изменено: {error}")
                self.api_error.emit(error)

        self.sync.workers.submit(action, success, failed)

    def dispose(self):
        self.disposed = True
        self.timer.stop()
        self.revision += 1
        for panel in self.panels:
            panel.disposed = True
            panel.revision += 1
