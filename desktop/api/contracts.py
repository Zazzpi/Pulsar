"""Validate containers consumed by Qt before storing or rendering API data."""
from desktop.api.client import ApiError


def validate_read_payload(path, payload):
    def require(condition):
        if not condition:
            raise ApiError("Сервер вернул неожиданный формат данных. Проверьте адрес и версию API.")

    def client(row):
        require(isinstance(row, dict))
        require(isinstance(row.get("id"), int) and not isinstance(row["id"], bool) and row["id"] > 0)
        require(isinstance(row.get("name", ""), str))

    require(isinstance(payload, dict))
    if path.endswith("/summary/"):
        require(isinstance(payload.get("stock", {}), dict))
        attention = payload.get("attention", [])
        require(isinstance(attention, list))
        for entry in attention:
            require(isinstance(entry, dict))
            require(isinstance(entry.get("message", entry.get("code", "")), str))
        return
    rows = payload.get("results")
    require(isinstance(rows, list) and len(rows) <= 100)
    require(all(isinstance(row, dict) for row in rows))
    require(isinstance(payload.get("has_next", False), bool))
    for row in rows:
        if path == "/api/clients/":
            client(row)
        elif path == "/api/watches/":
            require(isinstance(row.get("id"), int))
            if row.get("client") is not None:
                client(row["client"])
