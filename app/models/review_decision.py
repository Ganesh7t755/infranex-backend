import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class ReviewDecisionAction(str, enum.Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CONFIRM_REPAIR = "CONFIRM_REPAIR"
    REQUEST_REWORK = "REQUEST_REWORK"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"

class ReviewDecision(Base):
    __tablename__ = "complaint_review_decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(SQLEnum(ReviewDecisionAction), nullable=False)
    previous_status = Column(String(50), nullable=False)
    new_status = Column(String(50), nullable=False)
    reason = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    reviewer_id = Column(String(64), nullable=False, index=True)
    is_simulation = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    complaint = relationship("Complaint", back_populates="review_decisions")
