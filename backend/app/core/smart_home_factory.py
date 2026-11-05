from app.clients.hub_client import HubClient
from app.config import HUB_API_KEY, HUB_TIMEOUT_SECONDS, HUB_URL



def build_hub_client() -> HubClient | None:
    if not HUB_URL:
        return None
    if not HUB_API_KEY:
        raise RuntimeError("HUB_API_KEY must be configured when HUB_URL is set")
    return HubClient.create(HUB_URL, HUB_API_KEY, timeout=HUB_TIMEOUT_SECONDS)
