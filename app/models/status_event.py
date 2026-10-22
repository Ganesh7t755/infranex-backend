import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class ActorType(str, enum.Enum):
    CITIZEN = "CITIZEN"
    REVIEWER = "REVIEWER"
    SYSTEM = "SYSTEM"
    AUTHORITY = "AUTHORITY"


class ComplaintStatusEvent(Base):
    __tablename__ = "complaint_status_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    actor_type = Column(SQLEnum(ActorType), nullable=False, default=ActorType.CITIZEN)
    actor_id = Column(String(64), nullable=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    complaint = relationship("Complaint", back_populates="status_events")
