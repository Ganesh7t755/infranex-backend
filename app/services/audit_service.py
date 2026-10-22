import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        action: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        role: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[AuditLog]:
        try:
            entry = AuditLog(
                user_id=user_id,
                username=username,
                role=role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        except Exception as exc:
            db.rollback()
            logger.warning(f"Failed to record audit event '{action}': {exc}")
            return None
