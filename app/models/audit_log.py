import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from app.models.base import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(64), nullable=True, index=True)
    username = Column(String(64), nullable=True, index=True)
    role = Column(String(32), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=True, index=True)
    resource_id = Column(String(64), nullable=True, index=True)
    details = Column(String(2000), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
