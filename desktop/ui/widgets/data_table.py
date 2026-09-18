"""Compact read-only table; unknown API fields remain visible by their names."""

import json

from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from desktop.models.dto import display_time

LABELS = {
    "id": "ID", "product_id": "Товар ID", "sku": "Артикул", "name": "Название",
    "product_name": "Товар", "quantity": "Количество", "reserved_quantity": "Резерв",
    "available": "Доступно", "warehouse_id": "Склад ID", "cell_id": "Ячейка ID",
    "batch_id": "Партия ID", "box_id": "Короб ID", "status": "Статус",
    "order_type": "Тип заказа", "kind": "Вид приёмки", "movement_type": "Тип движения",
    "created_at": "Создано", "updated_at": "Обновлено", "received_at": "Принято",
    "shipped_at": "Отгружено", "confirmed_at": "Подтверждено", "client_id": "Клиент ID",
    "order_id": "Заказ ID", "receiving_id": "Приёмка ID", "shipment_id": "Отгрузка ID",
    "task_id": "Задание ID", "from_cell_id": "Из ячейки ID", "to_cell_id": "В ячейку ID",
    "reversal_of_id": "Сторно операции ID", "shipment_deadline": "Срок отгрузки",
    "planned_ship_date": "План отгрузки", "tracking_number": "Трек-номер",
    "planned_qty": "План", "actual_qty": "Факт", "return_reason": "Причина возврата",
    "marketplace_id": "Маркетплейс ID", "wave_id": "Волна ID", "assigned_to_id": "Исполнитель ID",
    "created_by_id": "Создал ID", "received_qty": "Принято", "is_defect": "Брак",
}

VALUES = {
    "new": "Новый", "confirmed": "Подтверждён", "picking": "Комплектация",
    "packed": "Упакован", "shipped": "Отгружен", "cancelled": "Отменён",
    "canceled": "Отменён", "draft": "Черновик", "in_receiving": "Идёт приёмка",
    "received": "Принят", "ready_to_ship": "Готов к отгрузке", "delivered": "Доставлен",
    "inbound": "Входящий", "outbound": "Исходящий", "supply": "Поставка",
    "return": "Возврат", "receiving": "Приёмка", "putaway": "Размещение",
    "move": "Перемещение", "shipment": "Отгрузка", "write_off": "Списание",
    "adjustment": "Корректировка", "assembly": "Сборка", "disassembly": "Разборка",
}


def cell_text(key: str, value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if key.endswith("_at") or key == "shipment_deadline":
        return display_time(str(value))
    if key in {"status", "order_type", "kind", "movement_type"}:
        return VALUES.get(str(value), str(value))
    return str(value)


class DataTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)

    def set_rows(self, rows: list[dict]):
        keys = list(dict.fromkeys(key for row in rows for key in row))
        self.clear()
        self.setColumnCount(len(keys))
        self.setHorizontalHeaderLabels([LABELS.get(key, key) for key in keys])
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, key in enumerate(keys):
                text = cell_text(key, row.get(key))
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.setItem(row_index, column, item)
        self.resizeColumnsToContents()
        for column in range(len(keys)):
            self.setColumnWidth(column, min(280, max(95, self.columnWidth(column))))
