import hashlib
import json
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from wms.repository import get_repository

from .models import ClientWatch

logger = logging.getLogger(__name__)
MISSING = object()


class WmsUnavailable(Exception):
    pass


def cached_read(resource, **params):
    """One canonical cache key includes all pagination, date and client filters."""
    encoded = json.dumps(
        {"mode": settings.WMS_MODE, "resource": resource, **params},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    key = "wms:v1:" + hashlib.sha256(encoded.encode()).hexdigest()
    try:
        value = cache.get(key, MISSING)
    except Exception as exc:
        logger.warning("Cache read failed type=%s", type(exc).__name__)
        value = MISSING
    if value is not MISSING:
        return value
    started = time.monotonic()
    try:
        repo = get_repository()
        if resource in {"clients", "client", "summary"}:
            value = getattr(repo, resource)(**params)
        else:
            value = repo.detail(resource=resource, **params)
    except Exception as exc:
        logger.error("WMS read failed resource=%s type=%s", resource, type(exc).__name__)
        raise WmsUnavailable from None
    finally:
        elapsed = time.monotonic() - started
        if elapsed >= 0.5:
            logger.warning("Slow WMS read resource=%s elapsed_ms=%d", resource, elapsed * 1000)
    try:
        cache.set(key, value, timeout=settings.CACHE_TTLS[resource])
    except Exception as exc:
        logger.warning("Cache write failed type=%s", type(exc).__name__)
    return value


def start_watch(user, client_id):
    """Serialize per user so concurrent requests cannot duplicate or extend a watch."""
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        now = timezone.now()
        ClientWatch.objects.filter(
            user=user, wms_client_id=client_id, is_active=True, ends_at__lte=now,
        ).update(is_active=False)
        existing = ClientWatch.objects.filter(
            user=user, wms_client_id=client_id, is_active=True,
        ).first()
        if existing:
            return existing, False
        return ClientWatch.objects.create(
            user=user, wms_client_id=client_id,
            started_at=now, ends_at=now + timedelta(days=90),
        ), True
