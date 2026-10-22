import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

class IncidentAssessment(Base):
    """
    Automated or advisory AI assessment of initial citizen-submitted incident evidence.
    
    Confidence Score Representation:
    - `confidence_score` is a normalized floating-point probability in the range [0.0, 1.0].
    - A score >= 0.90 indicates high routing confidence when accompanied by a category match
      and suitable evidence quality.
    - A value of `None` indicates the assessment was inconclusive, aborted, or unrated.
    - Raw heuristic checks or uncalibrated outputs must be flagged with `is_simulation=True`.
    """
    __tablename__ = "incident_assessments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(String(36), ForeignKey("complaint_evidence.id", ondelete="SET NULL"), nullable=True, index=True)
    
    provider_id = Column(String(64), nullable=False, default="heuristic_simulation")
    model_name = Column(String(64), nullable=False, default="infranex-suitability-v1")
    confidence_score = Column(Float, nullable=True)
    category_match = Column(Boolean, nullable=True)
    detected_category = Column(String(64), nullable=True)
    evidence_suitable = Column(Boolean, nullable=False, default=True)
    explanation = Column(Text, nullable=False)
    limitations = Column(String(1000), nullable=True)
    is_simulation = Column(Boolean, nullable=False, default=True)
    review_required = Column(Boolean, nullable=False, default=True)
    assessment_metadata = Column(JSON, nullable=False, default=dict)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    complaint = relationship("Complaint", back_populates="assessments")
    evidence = relationship("ComplaintEvidence", foreign_keys=[evidence_id])
