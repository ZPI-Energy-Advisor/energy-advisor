import datetime
import uuid
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base



class EnergyDataFile(Base):
    __tablename__ = "energy_data_files"

    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    SOURCE_METER = "meter"
    SOURCE_DEVICES = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    file_name = Column(String(255), nullable=False)
    uploaded_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    data_start = Column(Date, nullable=True)
    data_end = Column(Date, nullable=True)
    records_count = Column(Integer, nullable=True)
    source_type = Column(String(20), nullable=False, default=SOURCE_METER, server_default=SOURCE_METER)

    status = Column(String(20), nullable=False, default=STATUS_PROCESSING)
    error_message = Column(Text, nullable=True)
