from unittest.mock import Mock

import pytest
import requests

from desktop.api.client import ApiClient, ApiError
from desktop.config import normalize_origin


def response(status=200, payload=None):
    result = Mock(status_code=status)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.json.return_value = payload or {"results": []}
    return result


def test_request_timeout_headers_no_redirect_and_credentials_not_logged(monkeypatch, caplog):
    sender = Mock(side_effect=requests.Timeout("sensitive-pass"))
    monkeypatch.setattr(requests, "request", sender)
    api = ApiClient("https://warehouse.test", "private-token", timeout=7)
    with pytest.raises(ApiError, match="вовремя"):
        api.request("GET", "/api/clients/")
    kwargs = sender.call_args.kwargs
    assert kwargs["timeout"] == (3.05, 7)
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer private-token"
    assert "sensitive-pass" not in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 302])
def test_http_errors_are_actionable_and_dont_expose_response(monkeypatch, status):
    monkeypatch.setattr(requests, "request", Mock(return_value=response(status, {"error": "server-secret"})))
    with pytest.raises(ApiError) as caught:
        ApiClient("https://warehouse.test").request("GET", "/api/clients/")
    assert caught.value.status == status
    assert "server-secret" not in str(caught.value)


def test_malformed_json(monkeypatch):
    result = response()
    result.json.side_effect = ValueError("not json")
    monkeypatch.setattr(requests, "request", Mock(return_value=result))
    with pytest.raises(ApiError, match="JSON"):
        ApiClient("https://warehouse.test").request("GET", "/api/clients/")


def test_login_and_logout_keep_token_in_memory(monkeypatch):
    sender = Mock(side_effect=[
        response(payload={"token": "private", "user": {"id": 1, "username": "alice"}}),
        requests.ConnectionError(),
    ])
    monkeypatch.setattr(requests, "request", sender)
    api = ApiClient("https://warehouse.test")
    assert api.login("alice", "password") == {"id": 1, "username": "alice"}
    assert api.token == "private"
    with pytest.raises(ApiError):
        api.logout()
    assert api.token is None


@pytest.mark.parametrize("url", ["http://warehouse.test", "https://alice:secret@example.org", "https://example.org/api/", "https://example.org?q=token", "ftp://example.org"])
def test_unsafe_or_ambiguous_origins_rejected(url):
    with pytest.raises(ValueError):
        normalize_origin(url)


def test_equivalent_origins_share_namespace():
    assert normalize_origin("https://WAREHOUSE.test:443/") == "https://warehouse.test"
    assert normalize_origin("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
