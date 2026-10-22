import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class RepairVerificationOutcome(str, enum.Enum):
    LIKELY_RESOLVED = "LIKELY_RESOLVED"
    LIKELY_UNRESOLVED = "LIKELY_UNRESOLVED"
    INCONCLUSIVE = "INCONCLUSIVE"

class RepairVerification(Base):
    __tablename__ = "repair_verifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    before_evidence_id = Column(String(36), ForeignKey("complaint_evidence.id", ondelete="SET NULL"), nullable=True)
    after_evidence_id = Column(String(36), ForeignKey("complaint_evidence.id", ondelete="SET NULL"), nullable=True)
    
    outcome = Column(SQLEnum(RepairVerificationOutcome), nullable=False, index=True)
    explanation = Column(Text, nullable=False)
    observations = Column(JSON, nullable=False, default=list)
    evidence_quality = Column(String(255), nullable=False)
    limitations = Column(String(1000), nullable=False)
    
    provider_id = Column(String(64), nullable=False, default="mock_deterministic_v1")
    model_name = Column(String(64), nullable=False, default="infranex-heuristic-simulator-v1")
    is_simulation = Column(Boolean, nullable=False, default=True)
    human_review_required = Column(Boolean, nullable=False, default=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    complaint = relationship("Complaint", back_populates="verifications")
    before_evidence = relationship("ComplaintEvidence", foreign_keys=[before_evidence_id])
    after_evidence = relationship("ComplaintEvidence", foreign_keys=[after_evidence_id])
