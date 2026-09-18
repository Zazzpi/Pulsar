import hashlib
import json

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import caches
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .authentication import bearer_required
from .models import ApiToken


@csrf_exempt
def login(request):
    if request.method != "POST":
        return JsonResponse({"error": "Требуется POST."}, status=405)
    try:
        body = json.loads(request.body)
        username, password = body["username"], body["password"]
        if (not isinstance(username, str) or not isinstance(password, str)
                or not 1 <= len(username) <= 150 or not 1 <= len(password) <= 4096):
            raise ValueError
    except (ValueError, KeyError, TypeError, RecursionError):
        return JsonResponse({"error": "Укажите username и password."}, status=400)

    identity = request.META.get("REMOTE_ADDR", "unknown")
    key = "login:" + hashlib.sha256(identity.encode()).hexdigest()
    cache = caches["login_limits"]
    cache.add(key, 0, timeout=settings.LOGIN_RATE_WINDOW)
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=settings.LOGIN_RATE_WINDOW)
        attempts = 1
    if attempts > settings.LOGIN_RATE_LIMIT:
        response = JsonResponse({"error": "Слишком много попыток входа."}, status=429)
        response["Retry-After"] = str(settings.LOGIN_RATE_WINDOW)
        return response
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"error": "Неверное имя пользователя или пароль."}, status=401)
    return JsonResponse({
        "token": ApiToken.issue(user),
        "user": {"id": user.pk, "username": user.get_username()},
    })


@bearer_required
def logout(request):
    if request.method != "POST":
        return JsonResponse({"error": "Требуется POST."}, status=405)
    request.api_token.delete()
    return JsonResponse({"ok": True})
