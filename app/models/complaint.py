import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Enum as SQLEnum
from sqlalchemy.orm import relationship
from app.core.database import Base

class ComplaintCategory(str, enum.Enum):
    POTHOLE = "POTHOLE"
    GARBAGE = "GARBAGE"
    DAMAGED_ROAD = "DAMAGED_ROAD"
    BROKEN_STREETLIGHT = "BROKEN_STREETLIGHT"
    OTHER = "OTHER"

class ComplaintStatus(str, enum.Enum):
    # Initial & automated intake states
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    
    # Human Review states
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    
    # Authority & remediation states
    AUTHORITY_QUEUE = "AUTHORITY_QUEUE"
    ACTION_IN_PROGRESS = "ACTION_IN_PROGRESS"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    REPAIR_CLAIMED = "REPAIR_CLAIMED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    
    # Final & dispute states
    RESOLVED = "RESOLVED"
    RESOLVED_AFTER_REVIEW = "RESOLVED_AFTER_REVIEW"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    DISPUTED = "DISPUTED"
    REASSESSMENT_PENDING = "REASSESSMENT_PENDING"
    REASSESSMENT_COMPLETED = "REASSESSMENT_COMPLETED"

class LocationType(str, enum.Enum):
    GPS = "GPS"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"

class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reference_id = Column(String(32), unique=True, nullable=False, index=True)
    title = Column(String(120), nullable=False)
    category = Column(SQLEnum(ComplaintCategory), nullable=False, index=True)
    description = Column(String(2000), nullable=False)
    status = Column(SQLEnum(ComplaintStatus), nullable=False, default=ComplaintStatus.SUBMITTED, index=True)
    
    location_address = Column(String(255), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_type = Column(SQLEnum(LocationType), nullable=False, default=LocationType.UNKNOWN)
    
    citizen_id = Column(String(64), nullable=True, default="guest_citizen")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Multi-Domain Routing & Department Assignment (Stage 7C)
    service_domain = Column(String(50), nullable=True, index=True)
    assigned_department = Column(String(100), nullable=True)
    assignment_status = Column(String(50), nullable=False, default="UNASSIGNED")

    # Relationships
    evidence_items = relationship("ComplaintEvidence", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintEvidence.created_at")
    status_events = relationship("ComplaintStatusEvent", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintStatusEvent.created_at")
    assessments = relationship("IncidentAssessment", back_populates="complaint", cascade="all, delete-orphan", order_by="IncidentAssessment.created_at.desc()")
    verifications = relationship("RepairVerification", back_populates="complaint", cascade="all, delete-orphan", order_by="RepairVerification.created_at.desc()")
    disputes = relationship("ComplaintDispute", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintDispute.created_at.desc()")
    review_decisions = relationship("ReviewDecision", back_populates="complaint", cascade="all, delete-orphan", order_by="ReviewDecision.created_at.desc()")
    authority_actions = relationship("AuthorityAction", back_populates="complaint", cascade="all, delete-orphan", order_by="AuthorityAction.created_at.desc()")
    assignments = relationship("ComplaintAssignment", back_populates="complaint", cascade="all, delete-orphan", order_by="ComplaintAssignment.created_at.desc()")

