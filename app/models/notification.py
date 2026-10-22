import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class NotificationType(str, enum.Enum):
    STATUS_UPDATE = "STATUS_UPDATE"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    REPAIR_CLAIMED = "REPAIR_CLAIMED"
    RESOLVED = "RESOLVED"
    SYSTEM = "SYSTEM"

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), nullable=False, index=True)
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(120), nullable=False)
    message = Column(String(500), nullable=False)
    notification_type = Column(SQLEnum(NotificationType), nullable=False, default=NotificationType.STATUS_UPDATE)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    complaint = relationship("Complaint")

class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id = Column(String(64), primary_key=True)
    notify_status_updates = Column(Boolean, default=True, nullable=False)
    notify_evidence_requests = Column(Boolean, default=True, nullable=False)
    notify_resolution_alerts = Column(Boolean, default=True, nullable=False)
    notify_nearby_alerts = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
