from typing import List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.notification import Notification, NotificationType, NotificationPreference
from app.schemas.notification import NotificationPreferenceUpdate

class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        user_id: str,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.STATUS_UPDATE,
        complaint_id: Optional[str] = None
    ) -> Notification:
        # Prevent rapid duplicates (e.g., retried requests)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        existing = (
            self.db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.complaint_id == complaint_id,
                Notification.title == title,
                Notification.created_at >= cutoff
            )
            .first()
        )
        if existing:
            return existing

        notification = Notification(
            user_id=user_id,
            complaint_id=complaint_id,
            title=title,
            message=message,
            notification_type=notification_type,
            is_read=False,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def list_by_user(
        self,
        user_id: str,
        unread_only: bool = False,
        skip: int = 0,
        limit: int = 50
    ) -> List[Notification]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.is_read == False)
        return query.order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()

    def count_unread(self, user_id: str) -> int:
        return (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .count()
        )

    def mark_read(self, notification_id: str, user_id: str) -> Optional[Notification]:
        notification = (
            self.db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if notification and not notification.is_read:
            notification.is_read = True
            self.db.commit()
            self.db.refresh(notification)
        return notification

    def mark_all_read(self, user_id: str) -> int:
        updated_count = (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .update({Notification.is_read: True}, synchronize_session=False)
        )
        self.db.commit()
        return updated_count

    def get_or_create_preferences(self, user_id: str) -> NotificationPreference:
        prefs = (
            self.db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .first()
        )
        if not prefs:
            prefs = NotificationPreference(
                user_id=user_id,
                notify_status_updates=True,
                notify_evidence_requests=True,
                notify_resolution_alerts=True,
                notify_nearby_alerts=True,
                updated_at=datetime.now(timezone.utc)
            )
            self.db.add(prefs)
            self.db.commit()
            self.db.refresh(prefs)
        return prefs

    def update_preferences(self, user_id: str, update_in: NotificationPreferenceUpdate) -> NotificationPreference:
        prefs = self.get_or_create_preferences(user_id)
        if update_in.notify_status_updates is not None:
            prefs.notify_status_updates = update_in.notify_status_updates
        if update_in.notify_evidence_requests is not None:
            prefs.notify_evidence_requests = update_in.notify_evidence_requests
        if update_in.notify_resolution_alerts is not None:
            prefs.notify_resolution_alerts = update_in.notify_resolution_alerts
        if update_in.notify_nearby_alerts is not None:
            prefs.notify_nearby_alerts = update_in.notify_nearby_alerts
        prefs.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(prefs)
        return prefs
