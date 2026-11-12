import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.clients.hub_client import HubAuthError, HubClient, HubError, HubUnavailableError
from app.models.HomeConnection import HomeConnection
from app.models.User import User
from app.repositories.home_repository import HomeRepository
from app.schemas.smart_home import HomeStatus, HomeSync, HomeSyncStatus, HubDevice


logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "Hub Smart Home jest niedostępny. Urządzenia zostaną wysłane przy kolejnej operacji."
AUTH_MESSAGE = "Hub Smart Home odrzucił klucz HUB_API_KEY. Sprawdź konfigurację backendu i huba."
DISABLED_MESSAGE = "Symulacja Smart Home jest wyłączona."
NOT_CONNECTED_MESSAGE = "Dom nie jest podłączony. Podłącz dom, żeby zobaczyć jego stan."


def require_connected(home: HomeConnection, owner: User) -> None:
    """Stan domu i sterowanie nim mają sens tylko dla domu podłączonego przez właściciela."""
    if home.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_CONNECTED_MESSAGE)



def registry_hash(devices: list[HubDevice]) -> str:
    """Skrót treści PUT /home/devices: ten sam rejestr daje ten sam skrót."""
    canonical = json.dumps(HubClient.registry_payload(devices), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class HomeService:
    """Dom symulowany przez hub: właściciel, podłączenie i wysyłka rejestru urządzeń.

    Hub obsługuje jeden dom i nie zna użytkowników. Dom należy do konta z HUB_HOME_USER_EMAIL;
    hub ma mieć rejestr jego urządzeń, gdy dom jest podłączony, a pusty, gdy odłączony.
    Rejestr z bazy jest jedynym źródłem prawdy: każda wysyłka zastępuje rejestr w hubie aktualnym
    stanem bazy, więc nieudaną wystarczy powtórzyć przy dowolnej kolejnej operacji właściciela.
    """

    def __init__(self, repository: HomeRepository, hub_client: HubClient | None, owner_email: str | None):
        self.repository = repository
        self.hub_client = hub_client
        self.owner_email = owner_email

    @property
    def enabled(self) -> bool:
        return self.hub_client is not None

    def is_owner(self, user: User) -> bool:
        return self.enabled and self.owner_email is not None and user.email.strip().lower() == self.owner_email

    def require_owner(self, user: User) -> None:
        if not self.enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DISABLED_MESSAGE)
        if not self.is_owner(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dom Smart Home należy do innego konta.")

    def status(self, owner: User) -> HomeStatus:
        home = self.repository.get()
        devices = self._desired_registry(home, owner)
        digest = registry_hash(devices)
        return self._status(home, owner, self._in_sync(home, digest, devices), len(devices))

    def connect(self, owner: User) -> HomeStatus:
        home = self.repository.lock()
        if home.user_id != owner.id:
            home.user_id = owner.id
            home.connected_at = datetime.now(timezone.utc)
        return self._push_locked(home, owner, force=True)

    def disconnect(self, owner: User) -> HomeStatus:
        home = self.repository.lock()
        if home.user_id == owner.id:
            home.user_id = None
            home.connected_at = None
        return self._push_locked(home, owner, force=True)

    def sync_after_change(self, user: User) -> HomeSync | None:
        if not self.is_owner(user):
            return None
        result = self._push_locked(self.repository.lock(), user, force=False)
        return result.sync if result.connected else None

    def _push_locked(self, home: HomeConnection, owner: User, *, force: bool) -> HomeStatus:
        devices = self._desired_registry(home, owner)
        digest = registry_hash(devices)
        if force or not self._in_sync(home, digest, devices):
            try:
                self.hub_client.put_devices(devices)
            except HubError as error:
                logger.warning("Nie udało się wysłać rejestru urządzeń do huba: %s", error)
                home.sync_error = self._error_message(error)
            else:
                home.registry_hash = digest
                home.synced_at = datetime.now(timezone.utc)
                home.sync_error = None
        self.repository.commit()
        return self._status(home, owner, self._in_sync(home, digest, devices), len(devices))

    def _desired_registry(self, home: HomeConnection, owner: User) -> list[HubDevice]:
        # Po zmianie HUB_HOME_USER_EMAIL dom poprzedniego właściciela przestaje być podłączony.
        return self.repository.registry(owner.id) if home.user_id == owner.id else []

    @staticmethod
    def _in_sync(home: HomeConnection, digest: str, devices: list[HubDevice]) -> bool:
        if home.registry_hash is None:
            return not devices
        return digest == home.registry_hash

    @staticmethod
    def _status(home: HomeConnection, owner: User, synced: bool, devices_count: int) -> HomeStatus:
        return HomeStatus(
            connected=home.user_id == owner.id,
            connected_at=home.connected_at if home.user_id == owner.id else None,
            devices_count=devices_count,
            sync=HomeSync(
                status=HomeSyncStatus.SYNCED if synced else HomeSyncStatus.PENDING,
                synced_at=home.synced_at,
                # Nieudana ponowna wysyłka rejestru, który hub już ma, niczego nie zaległa.
                error=None if synced else home.sync_error,
            ),
        )

    @staticmethod
    def _error_message(error: HubError) -> str:
        if isinstance(error, HubUnavailableError):
            return UNAVAILABLE_MESSAGE
        if isinstance(error, HubAuthError):
            return AUTH_MESSAGE
        return f"Hub Smart Home odrzucił rejestr urządzeń: {error}"
