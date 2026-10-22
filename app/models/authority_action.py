import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base

class AuthorityAction(Base):
    """
    Traceable log of official actions taken by municipal authorities or dispatch units.
    """
    __tablename__ = "authority_actions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    complaint_id = Column(String(36), ForeignKey("complaints.id", ondelete="CASCADE"), nullable=False, index=True)
    
    authority_id = Column(String(64), nullable=False, index=True)
    department = Column(String(100), nullable=False)
    action_type = Column(String(50), nullable=False)
    work_order_reference = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    complaint = relationship("Complaint", back_populates="authority_actions")
