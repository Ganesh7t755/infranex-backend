from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus
from app.models.authority_action import AuthorityAction
from app.models.status_event import ActorType
from app.schemas.complaint import ComplaintUpdateStatus
from app.schemas.authority_action import (
    AuthorityActionType,
    AuthorityActionCreate,
    AuthorityAcknowledgeRequest,
    AuthorityDispatchRequest,
    AuthorityResolveRequest,
    AuthorityQueueItemResponse,
    AuthorityComplaintDetailResponse,
)
from app.schemas.evidence import EvidenceResponse
from app.schemas.authority_action import AuthorityActionResponse
from app.core.security import AuthorityIdentity
from app.services.complaint_service import ComplaintService, VALID_TRANSITIONS


ELIGIBLE_QUEUE_STATUSES = [
    ComplaintStatus.AUTHORITY_QUEUE,
    ComplaintStatus.ACTION_IN_PROGRESS,
    ComplaintStatus.REPAIR_IN_PROGRESS,
    ComplaintStatus.REWORK_REQUESTED,
]

ELIGIBLE_ACTION_STATUSES = {
    ComplaintStatus.AUTHORITY_QUEUE,
    ComplaintStatus.ACTION_IN_PROGRESS,
    ComplaintStatus.REPAIR_IN_PROGRESS,
    ComplaintStatus.REWORK_REQUESTED,
}


class AuthorityService:
    def __init__(self, db: Session):
        self.db = db
        self.complaint_service = ComplaintService(db)

    def get_authority_queue(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[ComplaintCategory] = None,
        status_filter: Optional[ComplaintStatus] = None,
        domain: Optional[str] = None,
        department: Optional[str] = None,
        assignment_status: Optional[str] = None,
    ) -> List[AuthorityQueueItemResponse]:
        """
        Retrieves complaints currently eligible for municipal authority attention,
        with pagination and multi-domain filtering.
        """
        query = self.db.query(Complaint)

        if status_filter:
            if status_filter not in ELIGIBLE_QUEUE_STATUSES:
                # Ineligible statuses do not appear in authority queue
                return []
            query = query.filter(Complaint.status == status_filter)
        else:
            query = query.filter(Complaint.status.in_(ELIGIBLE_QUEUE_STATUSES))

        if category:
            query = query.filter(Complaint.category == category)

        if domain:
            query = query.filter(Complaint.service_domain == domain.upper())

        if assignment_status:
            query = query.filter(Complaint.assignment_status == assignment_status.upper())

        if department:
            query = query.filter(Complaint.assigned_department.ilike(f"%{department}%"))

        complaints = query.order_by(Complaint.updated_at.desc()).offset(skip).limit(limit).all()

        results = []
        for c in complaints:
            latest_assessment = c.assessments[0] if c.assessments else None
            latest_action = c.authority_actions[0] if c.authority_actions else None

            results.append(
                AuthorityQueueItemResponse(
                    id=c.id,
                    reference_id=c.reference_id,
                    title=c.title,
                    category=c.category,
                    status=c.status,
                    location_address=c.location_address,
                    latitude=c.latitude,
                    longitude=c.longitude,
                    citizen_id=c.citizen_id,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                    evidence_count=len(c.evidence_items),
                    latest_confidence_score=latest_assessment.confidence_score if latest_assessment else None,
                    latest_action_type=latest_action.action_type if latest_action else None,
                    latest_work_order=latest_action.work_order_reference if latest_action else None,
                    service_domain=c.service_domain,
                    assigned_department=c.assigned_department,
                    assignment_status=c.assignment_status,
                )
            )
        return results

    def get_complaint_detail(self, complaint_id: str) -> AuthorityComplaintDetailResponse:
        """
        Retrieves full incident details for an authorized authority without leaking
        unrelated citizens' private personal information.
        """
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        latest_assessment = complaint.assessments[0] if complaint.assessments else None

        evidence_responses = [
            EvidenceResponse(
                id=e.id,
                complaint_id=e.complaint_id,
                evidence_type=e.evidence_type,
                file_name=e.file_name,
                file_size=e.file_size,
                mime_type=e.mime_type,
                is_public_approved=e.is_public_approved,
                file_path=e.file_path,
                created_at=e.created_at
            )
            for e in complaint.evidence_items
        ]

        action_responses = [
            AuthorityActionResponse(
                id=a.id,
                complaint_id=a.complaint_id,
                authority_id=a.authority_id,
                department=a.department,
                action_type=a.action_type,
                work_order_reference=a.work_order_reference,
                notes=a.notes,
                created_at=a.created_at
            )
            for a in complaint.authority_actions
        ]

        return AuthorityComplaintDetailResponse(
            id=complaint.id,
            reference_id=complaint.reference_id,
            title=complaint.title,
            category=complaint.category,
            status=complaint.status,
            description=complaint.description,
            location_address=complaint.location_address,
            latitude=complaint.latitude,
            longitude=complaint.longitude,
            location_type=complaint.location_type.value if hasattr(complaint.location_type, "value") else str(complaint.location_type),
            citizen_id=complaint.citizen_id,
            created_at=complaint.created_at,
            updated_at=complaint.updated_at,
            evidence_items=evidence_responses,
            authority_actions=action_responses,
            latest_confidence_score=latest_assessment.confidence_score if latest_assessment else None,
            is_assessment_simulation=latest_assessment.is_simulation if latest_assessment else None,
            service_domain=complaint.service_domain,
            assigned_department=complaint.assigned_department,
            assignment_status=complaint.assignment_status,
        )

    def record_action(
        self,
        complaint_id: str,
        action_in: AuthorityActionCreate,
        authority: AuthorityIdentity
    ) -> AuthorityAction:
        """
        Validates authority action, verifies lifecycle eligibility, prevents contradictory
        actions, enforces centralized status transitions, and transactionally persists
        an auditable AuthorityAction record.
        """
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        # 1. Eligibility validation
        if complaint.status not in ELIGIBLE_ACTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Complaint '{complaint_id}' is in status '{complaint.status.value}', which is not eligible for authority actions."
            )

        # 2. Contradictory / duplicate action validation
        if complaint.status == ComplaintStatus.AUTHORITY_QUEUE and action_in.action_type == AuthorityActionType.RESOLVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot directly resolve a complaint from AUTHORITY_QUEUE without acknowledging or dispatching work first."
            )

        if complaint.status in (ComplaintStatus.ACTION_IN_PROGRESS, ComplaintStatus.REPAIR_IN_PROGRESS) and action_in.action_type == AuthorityActionType.ACKNOWLEDGE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Complaint is already in '{complaint.status.value}'; redundant acknowledge action is not permitted."
            )

        # 3. Determine target lifecycle status
        target_status = action_in.new_status
        if not target_status:
            if action_in.action_type == AuthorityActionType.DISPATCH:
                target_status = ComplaintStatus.ACTION_IN_PROGRESS
            elif action_in.action_type == AuthorityActionType.START_WORK:
                target_status = ComplaintStatus.REPAIR_IN_PROGRESS
            elif action_in.action_type == AuthorityActionType.RESOLVE:
                target_status = ComplaintStatus.RESOLVED
            elif action_in.action_type == AuthorityActionType.REJECT:
                target_status = ComplaintStatus.REVIEW_REQUIRED
            elif action_in.action_type == AuthorityActionType.ACKNOWLEDGE:
                # Acknowledgment logs acceptance; status can remain in AUTHORITY_QUEUE or move if specified
                target_status = None

        # 4. Transactional execution: update complaint status and persist action record
        try:
            if target_status and target_status != complaint.status:
                self.complaint_service.transition_status(
                    complaint_id=complaint.id,
                    update_in=ComplaintUpdateStatus(
                        new_status=target_status,
                        actor_id=authority.authority_id,
                        notes=f"Authority Action ({action_in.action_type.value}): {action_in.notes or 'Status updated by municipal authority'}"
                    ),
                    actor_type=ActorType.AUTHORITY
                )

            action = AuthorityAction(
                complaint_id=complaint.id,
                authority_id=authority.authority_id,  # From server-validated identity context
                department=action_in.department or authority.department,
                action_type=action_in.action_type.value,
                work_order_reference=action_in.work_order_reference,
                notes=action_in.notes,
                created_at=datetime.now(timezone.utc)
            )
            self.db.add(action)
            self.db.commit()
            self.db.refresh(action)
            return action
        except Exception:
            self.db.rollback()
            raise

    def acknowledge_work(
        self,
        complaint_id: str,
        req: AuthorityAcknowledgeRequest,
        authority: AuthorityIdentity
    ) -> AuthorityAction:
        action_in = AuthorityActionCreate(
            action_type=AuthorityActionType.ACKNOWLEDGE,
            department=req.department or authority.department,
            notes=req.notes or "Municipal authority acknowledged complaint and queued for work allocation."
        )
        return self.record_action(complaint_id, action_in, authority)

    def dispatch_work(
        self,
        complaint_id: str,
        req: AuthorityDispatchRequest,
        authority: AuthorityIdentity
    ) -> AuthorityAction:
        action_in = AuthorityActionCreate(
            action_type=AuthorityActionType.DISPATCH,
            department=req.department or authority.department,
            work_order_reference=req.work_order_reference,
            notes=req.notes or "Work order generated and field crew dispatched.",
            new_status=ComplaintStatus.ACTION_IN_PROGRESS
        )
        return self.record_action(complaint_id, action_in, authority)

    def resolve_work(
        self,
        complaint_id: str,
        req: AuthorityResolveRequest,
        authority: AuthorityIdentity
    ) -> AuthorityAction:
        action_in = AuthorityActionCreate(
            action_type=AuthorityActionType.RESOLVE,
            department=req.department or authority.department,
            work_order_reference=req.work_order_reference,
            notes=req.notes,
            new_status=ComplaintStatus.RESOLVED
        )
        return self.record_action(complaint_id, action_in, authority)

    def get_actions(self, complaint_id: str) -> List[AuthorityAction]:
        """Retrieves chronological, auditable authority action history for a complaint."""
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )
        return (
            self.db.query(AuthorityAction)
            .filter(AuthorityAction.complaint_id == complaint_id)
            .order_by(AuthorityAction.created_at.desc())
            .all()
        )

    def get_action(self, complaint_id: str, action_id: str) -> AuthorityAction:
        """Retrieves a specific action record, strictly scoped to its parent complaint."""
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )
        action = (
            self.db.query(AuthorityAction)
            .filter(
                AuthorityAction.id == action_id,
                AuthorityAction.complaint_id == complaint_id
            )
            .first()
        )
        if not action:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Authority action '{action_id}' not found for complaint '{complaint_id}'"
            )
        return action
