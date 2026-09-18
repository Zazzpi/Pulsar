from collections.abc import Callable

from desktop.models.dto import CachedResponse
from desktop.services.client_service import ClientService
from desktop.workers.request_worker import WorkerPool


class SyncService:
    """Deliver a cached response synchronously, then optionally schedule refresh."""

    def __init__(self, service: ClientService, workers: WorkerPool):
        self.service, self.workers = service, workers

    def load(self, path: str, params: dict, show: Callable[[CachedResponse, bool], None], failed: Callable, loading: Callable):
        cached = self.service.cached(path, params)
        if cached is not None:
            show(cached, True)
        if self.service.offline:
            if cached is None:
                failed(RuntimeError("Эти данные ещё не сохранены на этом компьютере."))
            return
        loading(cached is not None)
        self.workers.submit(
            lambda: self.service.fetch(path, params),
            lambda result: show(result, False),
            failed,
        )
