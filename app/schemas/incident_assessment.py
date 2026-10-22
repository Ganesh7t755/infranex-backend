from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class IncidentAssessmentResponse(BaseModel):
    id: str
    complaint_id: str
    evidence_id: Optional[str] = None
    provider_id: str
    model_name: str
    confidence_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Calibrated probability score in range [0.0, 1.0], or null if unrated/inconclusive"
    )
    category_match: Optional[bool] = None
    detected_category: Optional[str] = None
    evidence_suitable: bool
    explanation: str
    limitations: Optional[str] = None
    is_simulation: bool
    review_required: bool
    assessment_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
