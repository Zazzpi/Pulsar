"""Demonstration data retains WMS column names and document relationships."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .services import (
    ACTIVE_ORDERS, ACTIVE_RECEIVINGS, RESOURCES, as_datetime, attention,
    date_range, paginated, pagination, stock_totals,
)


def demo_data(now) -> dict[str, list[dict]]:
    """Generate four clients and dates relative to today so the demo stays useful."""
    data = {table: [] for table in (
        "clients_client", "products_product", "stocks_stock", "orders_order",
        "receivings_receiving", "shipments_shipment", "movements_movement",
        "tasks_task", "orders_receivingrequest", "orders_shipmentrequest",
        "billing_billingcharge", "integrations_integration",
    )}

    def timestamp(days=0, hours=0):
        return (now - timedelta(days=days, hours=hours)).isoformat()

    for client_id, name in enumerate(("Ромашка", "Альфа Логистика", "Вектор", "Север Трейд"), 1):
        data["clients_client"].append({"id": client_id, "name": name,
                                      "inn": f"770000000{client_id}", "is_active": True})
        for index, product_name in enumerate(("Кабель USB-C", "Зарядное устройство"), 1):
            product_id = client_id * 10 + index
            data["products_product"].append({
                "id": product_id, "client_id": client_id, "sku": f"SKU-{product_id}",
                "name": product_name, "abc_class": "A" if index == 1 else "B", "is_active": True,
            })
            data["stocks_stock"].append({
                "product_id": product_id, "quantity": client_id * 120 + index * 30,
                "reserved_quantity": index * 20, "warehouse_id": 1,
                "cell_id": product_id, "batch_id": None, "box_id": None,
                "updated_at": timestamp(hours=1),
            })
        for index, status in enumerate(("new", "picking", "shipped", "cancelled"), 1):
            data["orders_order"].append({
                "id": client_id * 100 + index, "order_type": "outbound", "status": status,
                # An old open order demonstrates that activity is not date-filtered.
                "created_at": timestamp(days=120 if index == 1 else index),
                "shipment_deadline": timestamp(hours=-6 if index == 2 else 24),
                "planned_ship_date": now.date().isoformat(), "client_id": client_id,
                "marketplace_id": 1, "warehouse_id": 1, "wave_id": None,
            })
        for index, status in enumerate(("in_receiving", "received", "canceled"), 1):
            data["receivings_receiving"].append({
                "status": status, "kind": "supply", "client_id": client_id,
                "created_at": timestamp(days=index), "confirmed_at": timestamp(days=index, hours=-1),
                "received_at": timestamp(days=1) if status == "received" else None,
                "assigned_to_id": 1, "return_reason": "",
            })
        for index, status in enumerate(("ready_to_ship", "shipped"), 2):
            data["shipments_shipment"].append({
                "status": status, "created_at": timestamp(days=2, hours=index),
                "shipped_at": timestamp(days=1) if status == "shipped" else None,
                "order_id": client_id * 100 + index, "warehouse_id": 1,
                "tracking_number": f"DEMO-{client_id}-{index}",
            })
        for index in range(72):
            movement_type = ("receiving", "putaway", "picking", "shipment")[index % 4]
            data["movements_movement"].append({
                "movement_type": movement_type, "quantity": 10 + index % 5,
                "created_at": timestamp(hours=index + 1), "warehouse_id": 1,
                "product_id": client_id * 10 + 1 + index % 2, "created_by_id": 1,
                "order_id": client_id * 100 + 3 if movement_type == "shipment" else None,
                "receiving_id": None, "shipment_id": None, "task_id": None,
                "from_cell_id": None if movement_type == "receiving" else client_id * 10 + 1,
                "to_cell_id": None if movement_type == "shipment" else client_id * 10 + 2,
                "reversal_of_id": 1000 + client_id if index == 71 else None,
            })
        data["tasks_task"].append({
            "task_type": "picking", "status": "in_progress", "completed_at": None,
            "started_at": timestamp(hours=4), "deadline": timestamp(hours=2),
            "assigned_to_id": 1, "warehouse_id": 1, "client_id": client_id,
        })
        data["orders_receivingrequest"].append({
            "status": "submitted", "created_at": timestamp(hours=3),
            "contractor_id": client_id, "wms_receiving_id": None,
        })
        data["orders_shipmentrequest"].append({
            "status": "accepted", "created_at": timestamp(days=3),
            "contractor_id": client_id, "wms_order_id": client_id * 100 + 3,
        })
        for amount, reversal in (("1500.00", None), ("300.00", None), ("-300.00", 1000 + client_id)):
            data["billing_billingcharge"].append({
                "amount": amount, "created_at": timestamp(days=1), "source_type": "shipment",
                "contractor_id": client_id, "service_id": 1, "quantity": "1",
                "unit_price": amount, "reversal_of_id": reversal,
            })
        data["integrations_integration"].append({
            "is_active": True, "last_sync_status": "error" if client_id == 1 else "ok",
            "last_synced_at": timestamp(hours=3 if client_id == 1 else 0.1),
            "last_error": "Демонстрационная ошибка соединения" if client_id == 1 else "",
            "client_id": client_id, "type_id": 1,
        })
    return data


class MockRepository:
    def __init__(self, *, now=None, data=None):
        self.now = now or timezone.now()
        self.data = demo_data(self.now) if data is None else deepcopy(data)

    def clients(self, search: str = "", page: int = 1, page_size: int = 50) -> dict:
        limit, offset = pagination(page, page_size)
        needle = search.casefold()
        rows = sorted((r for r in self.data["clients_client"]
                       if needle in r["name"].casefold() or needle in (r["inn"] or "")),
                      key=lambda r: (r["name"], r["id"]))
        return paginated(deepcopy(rows[offset:offset + limit]), page, page_size)

    def client(self, client_id: int) -> dict | None:
        return next((deepcopy(r) for r in self.data["clients_client"] if r["id"] == client_id), None)

    def _related(self, client_id: int, resource: str) -> list[dict]:
        products = {p["id"]: p for p in self.data["products_product"] if p["client_id"] == client_id}
        orders = {o["id"] for o in self.data["orders_order"] if o["client_id"] == client_id}
        table = {"stock": "stocks_stock", "orders": "orders_order",
                 "receivings": "receivings_receiving", "shipments": "shipments_shipment",
                 "movements": "movements_movement"}[resource]
        result = []
        for source in self.data[table]:
            if resource in {"stock", "movements"}:
                product = products.get(source["product_id"])
                if product is None:
                    continue
                row = {**source, "sku": product["sku"], "name": product["name"]}
                if resource == "stock":
                    row["available_quantity"] = row["quantity"] - row["reserved_quantity"]
            else:
                if resource == "shipments":
                    if source["order_id"] not in orders:
                        continue
                elif source["client_id"] != client_id:
                    continue
                row = dict(source)
            result.append(row)
        return result

    def detail(self, client_id: int, resource: str, page: int = 1, page_size: int = 50,
               date_from=None, date_to=None) -> dict:
        if resource not in RESOURCES:
            raise ValueError("Неизвестный раздел WMS")
        limit, offset = pagination(page, page_size)
        rows = self._related(client_id, resource)
        if resource == "stock":
            rows.sort(key=lambda r: (r["sku"], r["product_id"], r["warehouse_id"], r["cell_id"]))
        else:
            start, end = date_range(date_from, date_to, now=self.now)
            rows = [r for r in rows if start <= as_datetime(r["created_at"]) < end]
            rows.sort(key=lambda r: (r["created_at"], r.get("id", 0)), reverse=True)
        return paginated(deepcopy(rows[offset:offset + limit]), page, page_size)

    def _metrics(self, client_id, start, end) -> dict:
        stock = self._related(client_id, "stock")
        moves = [r for r in self._related(client_id, "movements")
                 if start <= as_datetime(r["created_at"]) < end and r["reversal_of_id"] is None]
        return {
            "stock": stock_totals(sum(r["quantity"] for r in stock),
                                  sum(r["reserved_quantity"] for r in stock)),
            "active_orders": sum(r["status"] in ACTIVE_ORDERS for r in self._related(client_id, "orders")),
            "active_receivings": sum(r["status"] in ACTIVE_RECEIVINGS
                                     for r in self._related(client_id, "receivings")),
            "received_units": sum(r["quantity"] for r in moves if r["movement_type"] == "receiving"),
            "shipped_units": sum(r["quantity"] for r in moves if r["movement_type"] == "shipment"),
        }

    def summary(self, client_id: int) -> dict:
        start, end = self.now - timedelta(days=90), self.now
        deadline = end + timedelta(hours=getattr(settings, "DEADLINE_WARNING_HOURS", 24))
        stale = end - timedelta(hours=getattr(settings, "INTEGRATION_STALE_HOURS", 1))
        related = lambda table: [r for r in self.data[table]
                                 if r.get("client_id", r.get("contractor_id")) == client_id]
        integrations = [r for r in related("integrations_integration") if r["is_active"]]
        pending_requests = sum(
            r["status"] == "submitted" and r[field] is None
            for table, field in (("orders_receivingrequest", "wms_receiving_id"),
                                 ("orders_shipmentrequest", "wms_order_id")) for r in related(table)
        )
        counts = {
            "overdue_tasks": sum(r["deadline"] is not None and as_datetime(r["deadline"]) < end
                                 and r["status"] not in {"done", "canceled"} for r in related("tasks_task")),
            "deadline_orders": sum(r["shipment_deadline"] is not None
                                   and as_datetime(r["shipment_deadline"]) <= deadline
                                   and r["status"] in ACTIVE_ORDERS for r in related("orders_order")),
            "pending_requests": pending_requests,
            "receiving_in_progress": sum(r["status"] == "in_receiving" for r in related("receivings_receiving")),
            "integration_errors": sum(r["last_sync_status"] == "error" for r in integrations),
            "stale_integrations": sum(r["last_synced_at"] is None
                                      or as_datetime(r["last_synced_at"]) < stale for r in integrations),
        }
        billing = sum((Decimal(r["amount"]) for r in related("billing_billingcharge")
                       if start <= as_datetime(r["created_at"]) < end), Decimal("0.00"))
        shipments = sum(r["status"] in {"shipped", "delivered"} and r["shipped_at"] is not None
                        and start <= as_datetime(r["shipped_at"]) < end
                        for r in self._related(client_id, "shipments"))
        return {"client": self.client(client_id), **self._metrics(client_id, start, end),
                "shipments": shipments, "billing_total": str(billing),
                "attention": attention(counts), "updated_at": end.isoformat()}

    def metric_snapshot(self, client_id: int, day: date) -> dict:
        start = as_datetime(day)
        result = self._metrics(client_id, start, start + timedelta(days=1))
        stock = result.pop("stock")
        return {**{f"stock_{key}": value for key, value in stock.items()}, **result}
