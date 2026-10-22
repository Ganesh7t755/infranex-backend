import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class EvidenceType(str, enum.Enum):
    INITIAL_REPORT = "INITIAL_REPORT"
    REPAIR_CLAIM = "REPAIR_CLAIM"
    DISPUTE_SUPPORT = "DISPUTE_SUPPORT"

class ComplaintEvidence(Base):
    __tablename__ = "complaint_evidence"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_type = Column(SQLEnum(EvidenceType), nullable=False, default=EvidenceType.INITIAL_REPORT)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(100), nullable=False)
    is_public_approved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    complaint = relationship("Complaint", back_populates="evidence_items")
