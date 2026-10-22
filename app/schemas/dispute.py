from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from app.models.dispute import DisputeStatus

class DisputeCreate(BaseModel):
    reason: str = Field(..., min_length=5, max_length=1000, description="Detailed explanation of why the resolution is disputed")
    supporting_evidence_id: Optional[str] = Field(None, description="Optional ID of newly uploaded evidence supporting the dispute")

class DisputeResolve(BaseModel):
    outcome: DisputeStatus = Field(..., description="Reviewer decision: UPHELD (citizen dispute valid) or OVERTURNED (resolution valid)")
    reviewer_notes: str = Field(..., min_length=3, max_length=1000, description="Reviewer's assessment and findings")

class DisputeResponse(BaseModel):
    id: str
    complaint_id: str
    citizen_id: str
    reason: str
    supporting_evidence_id: Optional[str] = None
    status: DisputeStatus
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
