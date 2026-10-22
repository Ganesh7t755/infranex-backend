from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.evidence import EvidenceType

class EvidenceBase(BaseModel):
    evidence_type: EvidenceType = EvidenceType.INITIAL_REPORT
    file_name: str
    file_size: int
    mime_type: str
    is_public_approved: bool = False

class EvidenceCreate(EvidenceBase):
    file_path: str

class EvidenceResponse(EvidenceBase):
    id: str
    complaint_id: str
    file_path: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
