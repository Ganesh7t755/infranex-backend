from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.models.complaint import ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import EvidenceType

class PublicEvidenceResponse(BaseModel):
    id: str
    evidence_type: EvidenceType
    file_name: str
    file_size: int
    mime_type: str
    file_url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PublicComplaintSummary(BaseModel):
    id: str
    reference_id: str
    title: str
    category: ComplaintCategory
    status: ComplaintStatus
    location_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: LocationType
    created_at: datetime
    updated_at: datetime
    evidence_count: int = 0
    distance_km: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class PublicComplaintDetail(BaseModel):
    id: str
    reference_id: str
    title: str
    category: ComplaintCategory
    description: str
    status: ComplaintStatus
    location_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: LocationType
    created_at: datetime
    updated_at: datetime
    evidence_items: List[PublicEvidenceResponse] = []

    model_config = ConfigDict(from_attributes=True)
