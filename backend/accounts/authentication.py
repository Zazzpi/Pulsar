import hashlib
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ApiToken


def bearer_required(view):
    @csrf_exempt
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        kind, _, secret = header.partition(" ")
        token = None
        if kind.lower() == "bearer" and 20 <= len(secret) <= 256:
            token = ApiToken.objects.select_related("user").filter(
                digest=hashlib.sha256(secret.encode()).hexdigest(),
                expires_at__gt=timezone.now(),
                user__is_active=True,
            ).first()
        if token is None:
            response = JsonResponse({"error": "Требуется авторизация."}, status=401)
            response["WWW-Authenticate"] = "Bearer"
            return response
        request.api_user = token.user
        request.api_token = token
        return view(request, *args, **kwargs)

    return wrapped
