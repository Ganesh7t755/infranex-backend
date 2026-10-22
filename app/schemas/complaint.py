from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.complaint import ComplaintCategory, ComplaintStatus, LocationType
from app.schemas.evidence import EvidenceResponse
from app.schemas.status_event import StatusEventResponse
from app.schemas.dispute import DisputeResponse
from app.schemas.reviewer import ReviewDecisionResponse
from app.schemas.incident_assessment import IncidentAssessmentResponse
from app.schemas.authority_action import AuthorityActionResponse


class ComplaintBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=120, description="Brief summary of the issue")
    category: ComplaintCategory = Field(..., description="Category of civic infrastructure defect")
    description: str = Field(..., min_length=5, max_length=2000, description="Detailed description of the issue")
    location_address: Optional[str] = Field(None, max_length=255, description="Street address or landmark")
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="GPS latitude")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="GPS longitude")
    location_type: LocationType = Field(LocationType.UNKNOWN, description="Source of location info (GPS or MANUAL)")
    citizen_id: Optional[str] = Field("guest_citizen", description="Identifier of submitting citizen")

    @field_validator("location_type", mode="before")
    @classmethod
    def infer_or_validate_location_type(cls, v, info):
        return v

class ComplaintCreate(ComplaintBase):
    pass

class ComplaintUpdateStatus(BaseModel):
    new_status: ComplaintStatus
    actor_id: Optional[str] = "authorized_reviewer"
    notes: Optional[str] = Field(None, max_length=1000)

class ComplaintSummaryResponse(BaseModel):
    id: str
    reference_id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    location_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: LocationType
    citizen_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    evidence_count: int = 0
    latest_update: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class ComplaintDetailResponse(ComplaintBase):
    id: str
    reference_id: str
    status: ComplaintStatus
    created_at: datetime
    updated_at: datetime
    evidence_items: List[EvidenceResponse] = []
    status_events: List[StatusEventResponse] = []
    disputes: List[DisputeResponse] = []
    review_decisions: List[ReviewDecisionResponse] = []
    assessments: List[IncidentAssessmentResponse] = []
    authority_actions: List[AuthorityActionResponse] = []

    model_config = ConfigDict(from_attributes=True)


