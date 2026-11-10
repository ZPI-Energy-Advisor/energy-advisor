import logging

from app.repositories.home_event_repository import HomeEventRepository
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import HubEventBatch, HubEventsAccepted


logger = logging.getLogger(__name__)



class HomeEventService:
    """Webhook huba: zapis partii zdarzeń urządzeń.

    Hub ponawia całą partię po timeoucie albo 5xx, więc zapis jest idempotentny po event_id:
    zdarzenie, które już jest w bazie, jest pomijane i liczone jako duplikat.
    Zdarzenia należą do właściciela podłączonego domu; hub obsługuje jeden dom.
    """

    def __init__(self, event_repository: HomeEventRepository, home_repository: HomeRepository):
        self.event_repository = event_repository
        self.home_repository = home_repository

    def ingest(self, batch: HubEventBatch) -> HubEventsAccepted:
        owner_id = self.home_repository.get().user_id
        stored = self.event_repository.insert_new(owner_id, batch.events)
        self.event_repository.commit()
        duplicates = len(batch.events) - stored
        if owner_id is None and stored:
            logger.warning("Hub przysłał %d zdarzeń, gdy dom był odłączony", stored)
        return HubEventsAccepted(accepted=stored, duplicates=duplicates)
