import enum
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.schemas.evidence import EvidenceResponse


class AuthorityActionType(str, enum.Enum):
    ACKNOWLEDGE = "ACKNOWLEDGE"
    DISPATCH = "DISPATCH"
    START_WORK = "START_WORK"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVE = "RESOLVE"
    REJECT = "REJECT"


class AuthorityActionCreate(BaseModel):
    action_type: AuthorityActionType = Field(..., description="Action type: ACKNOWLEDGE, DISPATCH, START_WORK, IN_PROGRESS, RESOLVE, REJECT")
    department: Optional[str] = Field(None, max_length=100, description="Municipal department executing the action")
    work_order_reference: Optional[str] = Field(None, max_length=64, description="Work order or dispatch ticket reference")
    notes: Optional[str] = Field(None, max_length=2000, description="Field notes, status update or resolution details")
    new_status: Optional[ComplaintStatus] = Field(None, description="Optional target status transition")


class AuthorityAcknowledgeRequest(BaseModel):
    department: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)


class AuthorityDispatchRequest(BaseModel):
    department: Optional[str] = Field(None, max_length=100)
    work_order_reference: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = Field(None, max_length=2000)


class AuthorityResolveRequest(BaseModel):
    notes: str = Field(..., min_length=3, max_length=2000, description="Resolution notes detailing work completed")
    department: Optional[str] = Field(None, max_length=100)
    work_order_reference: Optional[str] = Field(None, max_length=64)


class AuthorityActionResponse(BaseModel):
    id: str
    complaint_id: str
    authority_id: str
    department: str
    action_type: str
    work_order_reference: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthorityQueueItemResponse(BaseModel):
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
    latest_confidence_score: Optional[float] = None
    latest_action_type: Optional[str] = None
    latest_work_order: Optional[str] = None
    service_domain: Optional[str] = None
    assigned_department: Optional[str] = None
    assignment_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AuthorityComplaintDetailResponse(BaseModel):
    id: str
    reference_id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    description: str
    location_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: str
    citizen_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    evidence_items: List[EvidenceResponse] = []
    authority_actions: List[AuthorityActionResponse] = []
    latest_confidence_score: Optional[float] = None
    is_assessment_simulation: Optional[bool] = None
    service_domain: Optional[str] = None
    assigned_department: Optional[str] = None
    assignment_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
