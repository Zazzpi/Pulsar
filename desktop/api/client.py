"""Small requests adapter. Call its methods only from a request worker."""

import logging
import json
from typing import Any

import requests

from desktop.config import normalize_origin

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, origin: str, token: str | None = None, timeout: float = 15):
        self.origin = normalize_origin(origin)
        self.token = token
        self.timeout = (3.05, timeout)

    def request(self, method: str, path: str, *, params: dict | None = None, data: dict | None = None) -> Any:
        if not path.startswith("/api/") or "?" in path or "#" in path:
            raise ValueError("Недопустимый путь API.")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = requests.request(
                method, self.origin + path, params=params, json=data,
                headers=headers, timeout=self.timeout, allow_redirects=False, stream=True,
            )
        except requests.Timeout as exc:
            logger.warning("HTTP timeout: %s %s", method, path)
            raise ApiError("Сервер не ответил вовремя. Данные могут быть устаревшими.") from exc
        except requests.RequestException as exc:
            logger.warning("HTTP connection failed: %s %s (%s)", method, path, type(exc).__name__)
            raise ApiError("Нет соединения с сервером. Проверьте адрес API и подключение.") from exc
        with response:
            if not 200 <= response.status_code < 300:
                logger.warning("HTTP error: %s %s status=%s", method, path, response.status_code)
                messages = {
                    400: "Сервер отклонил данные запроса.",
                    401: "Неверный логин или пароль, либо срок действия сессии истёк.",
                    403: "Недостаточно прав для выполнения действия.",
                    404: "Данные не найдены на сервере.",
                    409: "Данные были изменены. Обновите страницу.",
                    429: "Слишком много запросов. Повторите позже.",
                }
                raise ApiError(messages.get(response.status_code, "Ошибка сервера. Повторите запрос позже."), response.status_code)
            if response.status_code == 204:
                return None
            try:
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ApiError("Ответ сервера слишком большой. Уменьшите размер страницы.")
                payload = json.loads(raw)
            except requests.RequestException as exc:
                raise ApiError("Не удалось загрузить ответ сервера. Проверьте соединение.") from exc
            except (ValueError, RecursionError) as exc:
                raise ApiError("Сервер вернул некорректный JSON.") from exc
            if not isinstance(payload, (dict, list)):
                raise ApiError("Сервер вернул неожиданный формат данных.")
            return payload

    def login(self, username: str, password: str) -> dict:
        payload = self.request("POST", "/api/auth/login/", data={"username": username, "password": password})
        if (not isinstance(payload, dict) or not isinstance(payload.get("token"), str)
                or not payload["token"] or not payload["token"].isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in payload["token"])
                or not isinstance(payload.get("user"), dict)):
            raise ApiError("Ответ авторизации не содержит токен и пользователя.")
        user = payload["user"]
        if (not isinstance(user.get("id"), int) or isinstance(user["id"], bool) or user["id"] < 1
                or not isinstance(user.get("username"), str) or not user["username"]):
            raise ApiError("Ответ авторизации не содержит идентификатор пользователя.")
        self.token = payload["token"]
        return {"id": user["id"], "username": user["username"]}

    def logout(self) -> None:
        try:
            self.request("POST", "/api/auth/logout/")
        finally:
            self.token = None
