import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiToken(models.Model):
    """Only a digest is persisted; the bearer secret is returned once at login."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    @classmethod
    def issue(cls, user):
        secret = secrets.token_urlsafe(32)
        cls.objects.create(
            user=user,
            digest=hashlib.sha256(secret.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(hours=settings.TOKEN_TTL_HOURS),
        )
        return secret
