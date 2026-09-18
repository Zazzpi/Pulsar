from desktop.services.client_service import ClientService


class WatchService:
    def __init__(self, service: ClientService):
        self.service = service

    def start(self, client_id: int) -> dict:
        result = self.service.mutate("POST", "/api/watches/", {"wms_client_id": client_id})
        self.service.invalidate("/api/watches/")
        return result

    def stop(self, watch_id: int) -> None:
        self.service.mutate("DELETE", f"/api/watches/{watch_id}/")
        self.service.invalidate("/api/watches/")
