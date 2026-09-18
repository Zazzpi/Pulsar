from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDateEdit, QGridLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from desktop.models.dto import CachedResponse, display_time
from desktop.services.sync_service import SyncService
from desktop.ui.widgets.data_table import DataTable


def plain_label(text="") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class ResourcePanel(QWidget):
    api_error = pyqtSignal(object)

    def __init__(self, sync: SyncService, resource: str, page_size: int = 50):
        super().__init__()
        self.sync, self.resource, self.page_size = sync, resource, page_size
        self.client_id = None
        self.page, self.has_next = 1, False
        self.revision = 0
        self.busy = False
        self.loaded = False
        self.disposed = False
        self.layout = QVBoxLayout(self)
        self.status = plain_label("Выберите клиента")
        self.status.setObjectName("resourceStatus")
        self.layout.addWidget(self.status)

    def set_client(self, client_id: int):
        self.revision += 1
        self.client_id = client_id
        self.page, self.has_next, self.loaded, self.busy = 1, False, False, False
        self.status.setText("Данные загружаются при открытии вкладки")
        self.clear()

    def clear(self):
        pass

    def params(self) -> dict:
        return {} if self.resource == "summary" else {"page": self.page, "page_size": self.page_size}

    @property
    def path(self):
        return f"/api/clients/{self.client_id}/{self.resource}/"

    def refresh(self):
        if self.client_id is None or self.busy or self.disposed:
            return
        self.revision += 1
        revision = self.revision
        self.busy = True

        def active():
            return not self.disposed and self.revision == revision

        def show(response: CachedResponse, stale: bool):
            if not active():
                return
            self.loaded = True
            self.busy = stale and not self.sync.service.offline
            self.render(response.payload)
            prefix = "Сохранённые данные могут быть устаревшими. " if stale else ""
            self.status.setText(f"{prefix}Обновлено: {display_time(response.updated_at)}")

        def loading(has_cache: bool):
            if active():
                self.status.setText(self.status.text() + " · Обновление…" if has_cache else "Загрузка…")

        def failed(error):
            if not active():
                return
            self.busy = False
            prefix = "Данные могут быть устаревшими. " if self.loaded else ""
            old = self.status.text().replace(" · Обновление…", "") if self.loaded else ""
            self.status.setText(f"{prefix}{error}" + (f"\n{old}" if old else ""))
            self.api_error.emit(error)

        self.sync.load(self.path, self.params(), show, failed, loading)

    def render(self, payload):
        raise NotImplementedError

    def change_page(self, delta: int):
        self.revision += 1
        self.page = max(1, self.page + delta)
        self.busy, self.loaded = False, False
        self.clear()
        self.refresh()

    def pagination(self):
        row = QHBoxLayout()
        self.previous = QPushButton("← Назад")
        self.next = QPushButton("Далее →")
        self.page_label = plain_label("Страница 1")
        self.previous.clicked.connect(lambda: self.change_page(-1))
        self.next.clicked.connect(lambda: self.change_page(1))
        row.addWidget(self.previous)
        row.addWidget(self.page_label)
        row.addWidget(self.next)
        row.addStretch()
        self.layout.addLayout(row)
        self.update_pages()

    def update_pages(self):
        self.previous.setEnabled(self.page > 1)
        self.next.setEnabled(self.has_next)
        self.page_label.setText(f"Страница {self.page}")


class SummaryPanel(ResourcePanel):
    METRICS = (
        ("stock.total", "Всего единиц"), ("stock.reserved", "В резерве"),
        ("stock.available", "Доступно"), ("active_orders", "Активные заказы"),
        ("active_receivings", "Активные приёмки"), ("shipments", "Отгрузки за период"),
        ("received_units", "Принято за период"), ("shipped_units", "Отгружено за период"),
        ("billing_total", "Начислено за период"),
    )

    def __init__(self, sync):
        super().__init__(sync, "summary")
        self.metrics = {}
        grid = QGridLayout()
        for index, (key, title) in enumerate(self.METRICS):
            card = QWidget()
            card.setObjectName("metricCard")
            box = QVBoxLayout(card)
            box.addWidget(plain_label(title))
            value = plain_label("—")
            value.setObjectName("metricValue")
            box.addWidget(value)
            self.metrics[key] = value
            grid.addWidget(card, index // 3, index % 3)
        self.layout.addLayout(grid)
        self.period = plain_label("Потоки и начисления — за последние 90 дней; остатки и активные документы — сейчас.")
        self.layout.addWidget(self.period)
        self.layout.addWidget(plain_label("Требует внимания"))
        self.attention = QListWidget()
        self.layout.addWidget(self.attention)

    def clear(self):
        for label in self.metrics.values():
            label.setText("—")
        self.attention.clear()

    def render(self, payload):
        for key, label in self.metrics.items():
            value = payload
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            label.setText(str(value) if value is not None else "—")
        self.attention.clear()
        for entry in payload.get("attention", []):
            count = entry.get("count")
            self.attention.addItem(entry.get("message", entry.get("code", "")) + (f" ({count})" if count is not None else ""))
        if not self.attention.count():
            self.attention.addItem("Сигналы внимания не обнаружены")
        period = payload.get("period")
        if isinstance(period, dict):
            self.period.setText(f"Период: {period.get('from', '—')} — {period.get('to', '—')}")
        elif payload.get("period_days"):
            self.period.setText(f"Показатели за последние {payload['period_days']} дней")


class TablePanel(ResourcePanel):
    def __init__(self, sync, resource, page_size=50):
        super().__init__(sync, resource, page_size)
        self.date_from = self.date_to = None
        if resource != "stock":
            row = QHBoxLayout()
            self.date_from = QDateEdit(QDate.currentDate().addDays(-89))
            self.date_to = QDateEdit(QDate.currentDate())
            for widget in (self.date_from, self.date_to):
                widget.setCalendarPopup(True)
                widget.setDisplayFormat("dd.MM.yyyy")
            row.addWidget(plain_label("С"))
            row.addWidget(self.date_from)
            row.addWidget(plain_label("по"))
            row.addWidget(self.date_to)
            apply_button = QPushButton("Применить")
            apply_button.clicked.connect(self.apply_dates)
            row.addWidget(apply_button)
            row.addStretch()
            self.layout.addLayout(row)
        self.active_dates = self.selected_dates()
        self.table = DataTable()
        self.layout.addWidget(self.table)
        self.pagination()

    def selected_dates(self):
        if self.date_from is None:
            return {}
        # API uses an exclusive upper bound; the human-facing date is inclusive.
        return {"from": self.date_from.date().toString(Qt.DateFormat.ISODate), "to": self.date_to.date().addDays(1).toString(Qt.DateFormat.ISODate)}

    def apply_dates(self):
        if self.date_from.date() > self.date_to.date():
            self.status.setText("Начало периода не должно быть позже окончания.")
            return
        if self.date_from.date().daysTo(self.date_to.date()) >= 90:
            self.status.setText("Выберите период не более 90 дней.")
            return
        self.active_dates = self.selected_dates()
        self.page = 1
        self.change_page(0)

    def params(self):
        return {**super().params(), **self.active_dates}

    def clear(self):
        self.table.set_rows([])
        self.has_next = False
        self.update_pages()

    def render(self, payload):
        rows = payload.get("results", [])
        self.table.set_rows(rows)
        self.has_next = bool(payload.get("has_next"))
        self.update_pages()
        if not rows:
            self.table.setColumnCount(1)
            self.table.setHorizontalHeaderLabels(["Нет данных за выбранный период"])


class NotesPanel(ResourcePanel):
    def __init__(self, sync, page_size=50):
        super().__init__(sync, "notes", page_size)
        self.client_generation = 0
        self.saving = False
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        self.layout.addWidget(self.notes)
        self.pagination()
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("Заметка менеджера (до 5000 символов)")
        self.editor.setMaximumHeight(120)
        self.layout.addWidget(self.editor)
        self.save_button = QPushButton("Сохранить заметку")
        self.save_button.clicked.connect(self.save_note)
        self.layout.addWidget(self.save_button)
        self.update_access()

    def update_access(self):
        allowed = not self.sync.service.offline
        self.editor.setEnabled(allowed)
        self.save_button.setEnabled(allowed and not self.saving)

    def set_client(self, client_id):
        self.client_generation += 1
        self.saving = False
        super().set_client(client_id)
        self.editor.clear()
        self.update_access()

    def clear(self):
        self.notes.clear()
        self.has_next = False
        self.update_pages()

    def render(self, payload):
        self.notes.clear()
        for note in payload.get("results", []):
            self.notes.addItem(f"{display_time(note.get('created_at'))}\n{note.get('body', '')}")
        if not self.notes.count():
            self.notes.addItem("Заметок пока нет")
        self.has_next = bool(payload.get("has_next"))
        self.update_pages()

    def save_note(self):
        body = self.editor.toPlainText().strip()
        if not body or self.client_id is None or self.sync.service.offline or self.saving:
            return
        if len(body) > 5000:
            self.status.setText("Заметка не должна превышать 5000 символов.")
            return
        generation, path = self.client_generation, self.path
        self.saving = True
        self.save_button.setEnabled(False)
        self.status.setText("Сохранение заметки…")

        def create():
            result = self.sync.service.mutate("POST", path, {"body": body})
            self.sync.service.invalidate(path)
            return result

        def success(_result):
            if self.disposed or self.client_generation != generation:
                return
            self.saving = False
            if self.editor.toPlainText().strip() == body:
                self.editor.clear()
            self.update_access()
            self.page = 1
            self.change_page(0)

        def failed(error):
            if self.disposed or self.client_generation != generation:
                return
            self.saving = False
            self.update_access()
            self.status.setText(f"Заметка не сохранена: {error}")
            self.api_error.emit(error)

        self.sync.workers.submit(create, success, failed)
