"""Local API-shaped demonstration. No network, server, or WMS credentials."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from desktop.api.client import ApiError


class DemoApiClient:
    origin = "https://demo.pulsar.invalid"
    token = None
    demo = True
    user = {"id": "local-demo", "username": "Демонстрация"}

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.clients = [
            {"id": i, "name": name, "inn": f"770000000{i}", "is_active": True}
            for i, name in enumerate(("Ромашка", "Альфа Логистика", "Вектор"), 1)
        ]
        with closing(sqlite3.connect(self.state_path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS demo_state (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO demo_state VALUES ('watches', '{}')")
            db.execute("INSERT OR IGNORE INTO demo_state VALUES ('notes', '{}')")

    @staticmethod
    def _page(rows, params):
        page, size = int(params.get("page", 1)), int(params.get("page_size", 50))
        if not 1 <= page <= 1000 or not 1 <= size <= 100:
            raise ApiError("Некорректная страница.", 400)
        start = (page - 1) * size
        return {"results": rows[start:start + size], "page": page, "page_size": size,
                "has_next": start + size < len(rows)}

    def _state(self, key, update=None):
        with closing(sqlite3.connect(self.state_path, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT payload FROM demo_state WHERE key=?", [key]).fetchone()[0])
            result = update(state) if update else state
            if update:
                db.execute("UPDATE demo_state SET payload=? WHERE key=?", [json.dumps(state, ensure_ascii=False), key])
            return result

    def _client(self, client_id):
        return next((c for c in self.clients if c["id"] == int(client_id)), None)

    def _rows(self, client_id, resource):
        now = datetime.now(timezone.utc)
        stamp = lambda hours: (now - timedelta(hours=hours)).isoformat()
        if resource == "stock":
            return [{"product_id": client_id * 10 + i, "sku": f"DEMO-{client_id}-{i}",
                     "name": name, "quantity": 100 * client_id, "reserved_quantity": 20,
                     "available_quantity": 100 * client_id - 20, "warehouse_id": 1,
                     "cell_id": i, "batch_id": None, "box_id": None, "updated_at": stamp(1)}
                    for i, name in enumerate(("Кабель USB-C", "Зарядное устройство"), 1)]
        if resource == "orders":
            return [{"id": client_id * 100 + i, "order_type": "outbound", "status": status,
                     "created_at": stamp(24 + i), "shipment_deadline": stamp(-6),
                     "client_id": client_id, "warehouse_id": 1}
                    for i, status in enumerate(("confirmed", "picking"), 1)]
        if resource == "receivings":
            return [{"status": "in_receiving", "kind": "supply", "created_at": stamp(12),
                     "confirmed_at": stamp(10), "received_at": None, "client_id": client_id}]
        if resource == "shipments":
            return [{"status": "shipped", "created_at": stamp(30), "shipped_at": stamp(24),
                     "order_id": client_id * 100 + 3, "warehouse_id": 1, "tracking_number": "DEMO-12345"}]
        if resource == "movements":
            return [{"movement_type": "receiving" if i % 2 else "shipment", "quantity": 10,
                     "created_at": stamp(i), "product_id": client_id * 10 + 1,
                     "sku": f"DEMO-{client_id}-1", "warehouse_id": 1, "reversal_of_id": None}
                    for i in range(1, 73)]
        raise ApiError("Раздел демонстрации не найден.", 404)

    def request(self, method, path, *, params=None, data=None):
        params, data = params or {}, data or {}
        now = datetime.now(timezone.utc)
        if path == "/api/clients/" and method == "GET":
            query = str(params.get("q", "")).casefold()
            return self._page([c for c in self.clients if query in c["name"].casefold() or query in c["inn"]], params)
        if path == "/api/watches/":
            if method == "GET":
                rows = list(self._state("watches").values())
                for row in rows:
                    row["is_active"] = datetime.fromisoformat(row["ends_at"]) > now
                if params.get("wms_client_id"):
                    rows = [r for r in rows if r["wms_client_id"] == int(params["wms_client_id"])]
                return self._page(rows, params)
            if method == "POST":
                cid = int(data["wms_client_id"])
                client = self._client(cid)
                if client is None:
                    raise ApiError("Клиент не найден.", 404)
                def start(state):
                    old = state.get(str(cid))
                    if old and datetime.fromisoformat(old["ends_at"]) > now:
                        return old
                    state[str(cid)] = {"id": cid, "wms_client_id": cid, "client": client,
                                       "started_at": now.isoformat(), "ends_at": (now + timedelta(days=90)).isoformat(),
                                       "is_active": True}
                    return state[str(cid)]
                return self._state("watches", start)
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "watches"] and method == "DELETE":
            self._state("watches", lambda state: state.pop(parts[2], None))
            return {"ok": True}
        if len(parts) == 4 and parts[:2] == ["api", "clients"]:
            cid, resource = int(parts[2]), parts[3]
            client = self._client(cid)
            if not client:
                raise ApiError("Клиент не найден.", 404)
            if resource == "notes":
                if method == "GET":
                    return self._page(self._state("notes").get(str(cid), []), params)
                if method == "POST":
                    body = str(data.get("body", "")).strip()
                    if not 1 <= len(body) <= 5000:
                        raise ApiError("Заметка должна содержать от 1 до 5000 символов.", 400)
                    def note(state):
                        rows = state.setdefault(str(cid), [])
                        row = {"id": len(rows) + 1, "body": body, "created_at": now.isoformat()}
                        rows.insert(0, row)
                        return row
                    return self._state("notes", note)
            if method != "GET":
                raise ApiError("Действие недоступно.", 405)
            if resource == "summary":
                return {"client": client, "stock": {"total": 200 * cid, "reserved": 40, "available": 200 * cid - 40},
                        "active_orders": 2, "active_receivings": 1, "shipments": 1,
                        "received_units": 360, "shipped_units": 360, "billing_total": "1500.00",
                        "updated_at": now.isoformat(), "attention": [
                            {"code": "deadline_orders", "message": "Заказ приближается к сроку отгрузки", "count": 1},
                            {"code": "receiving_in_progress", "message": "Идёт приёмка товара", "count": 1},
                        ]}
            rows = self._rows(cid, resource)
            if resource != "stock":
                rows = [r for r in rows if str(params.get("from", "")) <= r["created_at"]
                        < str(params.get("to", "9999"))]
            return self._page(rows, params)
        raise ApiError("Действие недоступно в демонстрации.", 404)

    def logout(self):
        pass
