import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class ComplaintAssignment(Base):
    __tablename__ = "complaint_assignments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    service_domain = Column(String(50), nullable=False, index=True)
    department = Column(String(100), nullable=False, index=True)
    assignment_status = Column(String(50), nullable=False, default="ASSIGNED")
    assigned_by = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    complaint = relationship("Complaint", back_populates="assignments")
