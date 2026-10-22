from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.status_event import ActorType

class StatusEventBase(BaseModel):
    new_status: str
    actor_type: ActorType = ActorType.SYSTEM
    actor_id: Optional[str] = None
    notes: Optional[str] = None

class StatusEventCreate(StatusEventBase):
    previous_status: Optional[str] = None

class StatusEventResponse(StatusEventBase):
    id: str
    complaint_id: str
    previous_status: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
