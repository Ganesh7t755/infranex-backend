from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationType, NotificationPreference
from app.models.complaint import Complaint, ComplaintStatus
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)
from app.repositories.notification_repository import NotificationRepository

STATUS_NOTIFICATIONS = {
    ComplaintStatus.UNDER_REVIEW: (
        "Complaint Under Review",
        "Your report has been assigned and is being reviewed by city engineers.",
        NotificationType.STATUS_UPDATE
    ),
    ComplaintStatus.EVIDENCE_REQUESTED: (
        "More Evidence Requested",
        "Reviewers require additional photographic or location evidence for your report.",
        NotificationType.EVIDENCE_REQUESTED
    ),
    ComplaintStatus.REPAIR_IN_PROGRESS: (
        "Repair Work Started",
        "Public works department has scheduled and initiated physical repair work.",
        NotificationType.STATUS_UPDATE
    ),
    ComplaintStatus.REPAIR_CLAIMED: (
        "Repair Claimed by Contractor",
        "The contractor has claimed the repair is complete and submitted visual evidence.",
        NotificationType.REPAIR_CLAIMED
    ),
    ComplaintStatus.VERIFICATION_PENDING: (
        "Verification Pending",
        "Physical inspection or citizen review is pending to verify repair authenticity.",
        NotificationType.STATUS_UPDATE
    ),
    ComplaintStatus.RESOLVED_AFTER_REVIEW: (
        "Issue Resolved",
        "Civic defect repair has been inspected, verified, and officially closed.",
        NotificationType.RESOLVED
    ),
    ComplaintStatus.REWORK_REQUESTED: (
        "Rework Ordered",
        "Repair claim failed verification standards; rework has been ordered.",
        NotificationType.STATUS_UPDATE
    ),
    ComplaintStatus.DISPUTED: (
        "Complaint Disputed",
        "A formal dispute has been filed regarding the repair quality or claim.",
        NotificationType.STATUS_UPDATE
    ),
}

class NotificationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationRepository(db)

    def list_user_notifications(
        self,
        user_id: str,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 50
    ) -> NotificationListResponse:
        items = self.repo.list_by_user(user_id=user_id, unread_only=unread_only, skip=skip, limit=limit)
        unread_count = self.repo.count_unread(user_id=user_id)
        return NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in items],
            unread_count=unread_count
        )

    def mark_notification_read(self, notification_id: str, user_id: str) -> NotificationResponse:
        notification = self.repo.mark_read(notification_id=notification_id, user_id=user_id)
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or does not belong to the user"
            )
        return NotificationResponse.model_validate(notification)

    def mark_all_read(self, user_id: str) -> dict:
        count = self.repo.mark_all_read(user_id=user_id)
        return {"status": "success", "marked_read_count": count}

    def get_preferences(self, user_id: str) -> NotificationPreferenceResponse:
        prefs = self.repo.get_or_create_preferences(user_id)
        return NotificationPreferenceResponse.model_validate(prefs)

    def update_preferences(self, user_id: str, update_in: NotificationPreferenceUpdate) -> NotificationPreferenceResponse:
        prefs = self.repo.update_preferences(user_id, update_in)
        return NotificationPreferenceResponse.model_validate(prefs)

    def notify_status_change(self, complaint: Complaint, new_status: ComplaintStatus) -> Optional[Notification]:
        user_id = complaint.citizen_id
        if not user_id:
            return None

        # Check preferences
        prefs = self.repo.get_or_create_preferences(user_id)
        if not prefs.notify_status_updates:
            return None

        if new_status in STATUS_NOTIFICATIONS:
            title, default_msg, notif_type = STATUS_NOTIFICATIONS[new_status]
            message = f"[{complaint.reference_id}] {complaint.title}: {default_msg}"
            return self.repo.create(
                user_id=user_id,
                title=title,
                message=message,
                notification_type=notif_type,
                complaint_id=complaint.id
            )
        return None
