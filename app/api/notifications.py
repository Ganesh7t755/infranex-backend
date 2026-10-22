from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api/notifications", tags=["In-App Notifications"])

def get_current_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_citizen_id: Optional[str] = Header(None, alias="X-Citizen-ID"),
    user_id: Optional[str] = Query(None),
    citizen_id: Optional[str] = Query(None)
) -> str:
    # Resolve user identity from custom headers or query params, default to guest_citizen
    return x_user_id or x_citizen_id or user_id or citizen_id or "guest_citizen"

@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List in-app notifications and unread count for authenticated user"
)
def list_notifications(
    unread_only: bool = Query(False, description="Filter for unread notifications only"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    service = NotificationService(db)
    return service.list_user_notifications(
        user_id=current_user,
        unread_only=unread_only,
        skip=skip,
        limit=limit
    )

@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark a specific notification as read"
)
def mark_notification_read(
    notification_id: str,
    current_user: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    service = NotificationService(db)
    return service.mark_notification_read(notification_id=notification_id, user_id=current_user)

@router.post(
    "/mark-all-read",
    summary="Mark all unread notifications as read for current user"
)
def mark_all_read(
    current_user: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    service = NotificationService(db)
    return service.mark_all_read(user_id=current_user)

@router.get(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Get user notification preferences"
)
def get_preferences(
    current_user: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    service = NotificationService(db)
    return service.get_preferences(user_id=current_user)

@router.put(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Update user notification preferences"
)
def update_preferences(
    update_in: NotificationPreferenceUpdate,
    current_user: str = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    service = NotificationService(db)
    return service.update_preferences(user_id=current_user, update_in=update_in)
