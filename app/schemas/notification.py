from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.models.notification import NotificationType

class NotificationResponse(BaseModel):
    id: str
    user_id: str
    complaint_id: Optional[str] = None
    title: str
    message: str
    notification_type: NotificationType
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    unread_count: int

class NotificationPreferenceResponse(BaseModel):
    user_id: str
    notify_status_updates: bool
    notify_evidence_requests: bool
    notify_resolution_alerts: bool
    notify_nearby_alerts: bool
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class NotificationPreferenceUpdate(BaseModel):
    notify_status_updates: Optional[bool] = None
    notify_evidence_requests: Optional[bool] = None
    notify_resolution_alerts: Optional[bool] = None
    notify_nearby_alerts: Optional[bool] = None

class EvidenceModerationUpdate(BaseModel):
    is_public_approved: bool
