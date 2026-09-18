from django.conf import settings
from django.db import models


class ClientWatch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    wms_client_id = models.PositiveBigIntegerField()
    started_at = models.DateTimeField()
    ends_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [models.UniqueConstraint(
            fields=["user", "wms_client_id"], condition=models.Q(is_active=True),
            name="one_active_watch_per_user_client",
        )]


class ClientNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    wms_client_id = models.PositiveBigIntegerField(db_index=True)
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ClientDailyMetric(models.Model):
    """Daily snapshots belong to this application, never to the WMS database."""

    wms_client_id = models.PositiveBigIntegerField()
    date = models.DateField()
    stock_total = models.DecimalField(max_digits=24, decimal_places=4)
    stock_reserved = models.DecimalField(max_digits=24, decimal_places=4)
    stock_available = models.DecimalField(max_digits=24, decimal_places=4)
    received_units = models.DecimalField(max_digits=24, decimal_places=4)
    shipped_units = models.DecimalField(max_digits=24, decimal_places=4)
    active_orders = models.PositiveIntegerField()
    active_receivings = models.PositiveIntegerField()
    captured_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(
            fields=["wms_client_id", "date"], name="one_metric_per_client_day",
        )]
