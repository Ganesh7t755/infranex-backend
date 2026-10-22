from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.models.review_decision import ReviewDecisionAction

class ReviewDecisionCreate(BaseModel):
    action: ReviewDecisionAction = Field(..., description="Action: CONFIRM_REPAIR, REQUEST_REWORK, or REQUEST_EVIDENCE")
    reason: str = Field(..., min_length=5, max_length=1000, description="Official justification for the decision")
    notes: Optional[str] = Field(None, max_length=2000, description="Optional reviewer internal or public notes")

class ReviewDecisionResponse(BaseModel):
    id: str
    complaint_id: str
    action: ReviewDecisionAction
    previous_status: str
    new_status: str
    reason: str
    notes: Optional[str] = None
    reviewer_id: str
    is_simulation: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ReviewQueueItemResponse(BaseModel):
    id: str
    reference_id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    location_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    citizen_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    evidence_count: int
    has_before_after: bool
    latest_ai_outcome: Optional[str] = None
    latest_ai_provider: Optional[str] = None
    is_ai_simulation: Optional[bool] = None
    pending_dispute_id: Optional[str] = None
    review_state: str = Field(..., description="Calculated review state: NEEDS_REVIEW, DISPUTED, IN_PROGRESS, RESOLVED")

    model_config = ConfigDict(from_attributes=True)
