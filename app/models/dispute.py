import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class DisputeStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"

class ComplaintDispute(Base):
    __tablename__ = "complaint_disputes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    citizen_id = Column(String(64), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    supporting_evidence_id = Column(String(36), ForeignKey("complaint_evidence.id", ondelete="SET NULL"), nullable=True)
    status = Column(SQLEnum(DisputeStatus), nullable=False, default=DisputeStatus.PENDING_REVIEW, index=True)
    
    reviewer_id = Column(String(64), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # Relationships
    complaint = relationship("Complaint", back_populates="disputes")
    supporting_evidence = relationship("ComplaintEvidence", foreign_keys=[supporting_evidence_id])
