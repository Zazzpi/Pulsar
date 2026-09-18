import logging

from django.db import DatabaseError
from django.core.exceptions import RequestDataTooBig, SuspiciousOperation
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class SafeApiErrorsMiddleware(MiddlewareMixin):
    """Do not disclose SQL, credentials, connection strings or exception text."""

    def process_exception(self, request, exception):
        if not request.path.startswith("/api/"):
            return None
        if isinstance(exception, RequestDataTooBig):
            return JsonResponse({"error": "Слишком большой запрос."}, status=413)
        if isinstance(exception, SuspiciousOperation):
            return JsonResponse({"error": "Некорректный запрос."}, status=400)
        logger.error("API failure type=%s", type(exception).__name__)
        status = 503 if isinstance(exception, DatabaseError) else 500
        return JsonResponse({"error": "Сервис временно недоступен."}, status=status)

    def process_response(self, request, response):
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
        return response
