from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.models.repair_verification import RepairVerificationOutcome

class RepairVerificationRequest(BaseModel):
    before_evidence_id: Optional[str] = None
    after_evidence_id: Optional[str] = None

class RepairVerificationResponse(BaseModel):
    id: str
    complaint_id: str
    outcome: RepairVerificationOutcome
    explanation: str
    observations: List[str] = []
    evidence_quality: str
    limitations: str
    provider_id: str
    model_name: str
    is_simulation: bool
    human_review_required: bool
    before_evidence_id: Optional[str] = None
    after_evidence_id: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
