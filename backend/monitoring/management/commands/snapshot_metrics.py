import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from monitoring.models import ClientDailyMetric, ClientWatch
from wms.repository import get_repository

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Snapshot current stock/activity and today's UTC movements for watched clients."

    def handle(self, *args, **options):
        now = timezone.now()
        # Distinct clients, so two managers watching one client cause one WMS read.
        client_ids = ClientWatch.objects.filter(
            is_active=True, ends_at__gt=now,
        ).order_by().values_list("wms_client_id", flat=True).distinct()
        repo = get_repository()
        count, failures = 0, 0
        for client_id in client_ids.iterator(chunk_size=100):
            try:
                values = repo.metric_snapshot(client_id, now.date())
                if values is None:
                    failures += 1
                    continue
                ClientDailyMetric.objects.update_or_create(
                    wms_client_id=client_id, date=now.date(), defaults=values,
                )
                count += 1
            except Exception as exc:
                failures += 1
                logger.error("Metric snapshot failed client_id=%d type=%s", client_id, type(exc).__name__)
        self.stdout.write(f"Snapshots saved: {count}; failed: {failures}.")
        if failures:
            raise CommandError("Some snapshots could not be collected; see safe server logs")
