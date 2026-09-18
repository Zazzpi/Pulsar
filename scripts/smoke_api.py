"""Exercise the local DEMO API without printing credentials or tokens."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    env = dict(
        line.split("=", 1)
        for line in (root / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    url = args.url.rstrip("/")
    session = requests.Session()

    def call(method: str, path: str, **kwargs):
        response = session.request(method, url + path, timeout=20, **kwargs)
        assert response.ok, f"{method} {path}: HTTP {response.status_code}"
        return response.json() if response.content else None

    call("GET", "/api/health/")
    assert session.get(url + "/api/clients/", timeout=10).status_code == 401
    auth = call("POST", "/api/auth/login/", json={
        "username": env["DEMO_USERNAME"], "password": env["DEMO_PASSWORD"],
    })
    session.headers["Authorization"] = f"Bearer {auth['token']}"
    first = call("GET", "/api/clients/", params={"page_size": 1})
    assert len(first["results"]) == 1 and first["has_next"]
    second = call("GET", "/api/clients/", params={"page_size": 1, "page": 2})
    client = first["results"][0]
    assert second["results"][0]["id"] != client["id"]
    cid = client["id"]
    found = call("GET", "/api/clients/", params={"q": client["name"]})
    assert cid in [row["id"] for row in found["results"]]
    summary = call("GET", f"/api/clients/{cid}/summary/")
    stock = summary["stock"]
    assert int(stock["available"]) == int(stock["total"]) - int(stock["reserved"])
    watch = call("POST", "/api/watches/", json={"wms_client_id": cid})
    assert datetime.fromisoformat(watch["ends_at"].replace("Z", "+00:00")) - datetime.fromisoformat(
        watch["started_at"].replace("Z", "+00:00")
    ) == timedelta(days=90)
    again = call("POST", "/api/watches/", json={"wms_client_id": cid})
    assert again["id"] == watch["id"]
    assert any(w["wms_client_id"] == cid for w in call("GET", "/api/watches/")["results"])
    for resource in ("stock", "orders", "receivings", "shipments", "movements"):
        detail = call("GET", f"/api/clients/{cid}/{resource}/", params={"page_size": 1})
        assert len(detail["results"]) <= 1
        assert detail["page"] == 1
        print(f"OK {resource}")
    note = call("POST", f"/api/clients/{cid}/notes/", json={"body": "Проверка DEMO API: связаться с клиентом."})
    notes = call("GET", f"/api/clients/{cid}/notes/")["results"]
    assert any(row["id"] == note["id"] for row in notes)
    call("POST", "/api/auth/logout/")
    assert session.get(url + "/api/clients/", timeout=10).status_code == 401
    print("OK auth, search, pagination, summary, watch 90 days, notes, logout")


if __name__ == "__main__":
    main()
