from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class DeviceInstanceFile(Base):
    """Urządzenie występuje w pliku, także wtedy, gdy plik nie ma dla niego żadnej akcji."""

    __tablename__ = "device_instance_files"

    device_instance_id = Column(
        UUID(as_uuid=True),
        ForeignKey("device_instances.id", ondelete="CASCADE"),
        primary_key=True,
    )
    energy_data_file_id = Column(
        UUID(as_uuid=True),
        ForeignKey("energy_data_files.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
