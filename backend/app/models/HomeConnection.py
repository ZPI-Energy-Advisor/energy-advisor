from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class HomeConnection(Base):
    """
    Hub obsługuje jeden dom, więc tabela ma zawsze dokładnie jeden wiersz.
    Blokada tego wiersza szereguje wysyłki rejestru: ostatnia wysłana wersja jest
    zawsze najnowszym stanem bazy.
    """

    __tablename__ = "home_connection"
    __table_args__ = (CheckConstraint("id = 1", name="ck_home_connection_single_row"),)

    SINGLE_ROW_ID = 1

    id = Column(SmallInteger, primary_key=True)
    # Podłączony właściciel; NULL = dom odłączony i hub ma mieć pusty rejestr.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    connected_at = Column(DateTime(timezone=True), nullable=True)

    # Skrót rejestru, który hub ostatnio przyjął; NULL = nie wiadomo, co hub ma.
    # Rejestr z bazy o innym skrócie czeka na wysyłkę.
    registry_hash = Column(String(64), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    # Powód ostatniej nieudanej wysyłki; czyszczony po udanej.
    sync_error = Column(Text, nullable=True)
