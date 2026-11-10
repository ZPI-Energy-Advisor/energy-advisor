import logging

from app.clients.hub_client import HubClient
from app.config import HUB_API_KEY, HUB_TIMEOUT_SECONDS, HUB_URL


logger = logging.getLogger(__name__)



def build_hub_client() -> HubClient | None:
    if not HUB_URL:
        return None
    if not HUB_API_KEY:
        raise RuntimeError("HUB_API_KEY must be configured when HUB_URL is set")
    return HubClient.create(HUB_URL, HUB_API_KEY, timeout=HUB_TIMEOUT_SECONDS)


def build_app_hub_client() -> HubClient | None:
    try:
        return build_hub_client()
    except RuntimeError as error:
        logger.error("Smart Home wyłączony: %s", error)
        return None
