from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.models.dispute import ComplaintDispute, DisputeStatus
from app.models.review_decision import ReviewDecision, ReviewDecisionAction
from app.models.notification import NotificationType
from app.models.assignment import ComplaintAssignment
from app.schemas.reviewer import (
    ReviewDecisionCreate,
    ReviewQueueItemResponse,
)
from app.schemas.dispute import (
    DisputeCreate,
    DisputeResolve,
)
from app.core.security import ReviewerIdentity
from app.services.complaint_service import VALID_TRANSITIONS
from app.services.notification_service import NotificationService

class ReviewerService:
    def __init__(self, db: Session):
        self.db = db

    def get_review_queue(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[ComplaintCategory] = None,
        status_filter: Optional[ComplaintStatus] = None,
        review_state: Optional[str] = None,
    ) -> List[ReviewQueueItemResponse]:
        query = self.db.query(Complaint)

        if category:
            query = query.filter(Complaint.category == category)

        if status_filter:
            query = query.filter(Complaint.status == status_filter)
        else:
            # By default show items requiring human reviewer attention
            default_attention_statuses = [
                ComplaintStatus.SUBMITTED,
                ComplaintStatus.UNDER_REVIEW,
                ComplaintStatus.REVIEW_REQUIRED,
                ComplaintStatus.EVIDENCE_REQUESTED,
                ComplaintStatus.REPAIR_CLAIMED,
                ComplaintStatus.VERIFICATION_PENDING,
                ComplaintStatus.DISPUTED,
                ComplaintStatus.REASSESSMENT_PENDING,
                ComplaintStatus.REWORK_REQUESTED,
            ]
            query = query.filter(Complaint.status.in_(default_attention_statuses))

        complaints = query.order_by(Complaint.updated_at.desc()).offset(skip).limit(limit).all()

        results = []
        for c in complaints:
            # Check for before and after evidence
            initial_count = sum(1 for e in c.evidence_items if e.evidence_type == EvidenceType.INITIAL_REPORT)
            repair_count = sum(1 for e in c.evidence_items if e.evidence_type == EvidenceType.REPAIR_CLAIM)
            has_before_after = (initial_count > 0 and repair_count > 0)

            # Latest AI verification
            latest_ai_outcome = None
            latest_ai_provider = None
            is_ai_sim = None
            if c.verifications:
                latest_v = c.verifications[0]
                latest_ai_outcome = latest_v.outcome.value
                latest_ai_provider = latest_v.provider_id
                is_ai_sim = latest_v.is_simulation

            # Pending dispute
            pending_dispute = next((d for d in c.disputes if d.status == DisputeStatus.PENDING_REVIEW), None)
            pending_dispute_id = pending_dispute.id if pending_dispute else None

            # Calculate review state
            if c.status == ComplaintStatus.DISPUTED:
                calc_state = "DISPUTED"
            elif c.status in (ComplaintStatus.VERIFICATION_PENDING, ComplaintStatus.REPAIR_CLAIMED):
                calc_state = "PENDING_VERIFICATION"
            elif c.status in (ComplaintStatus.SUBMITTED, ComplaintStatus.UNDER_REVIEW, ComplaintStatus.REVIEW_REQUIRED):
                calc_state = "NEEDS_REVIEW"
            elif c.status == ComplaintStatus.REWORK_REQUESTED:
                calc_state = "REWORK"
            elif c.status in (ComplaintStatus.RESOLVED_AFTER_REVIEW, ComplaintStatus.REASSESSMENT_COMPLETED):
                calc_state = "RESOLVED"
            else:
                calc_state = "IN_PROGRESS"

            # Optional filter by calculated review state
            if review_state and calc_state.upper() != review_state.upper():
                continue

            results.append(
                ReviewQueueItemResponse(
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
                    has_before_after=has_before_after,
                    latest_ai_outcome=latest_ai_outcome,
                    latest_ai_provider=latest_ai_provider,
                    is_ai_simulation=is_ai_sim,
                    pending_dispute_id=pending_dispute_id,
                    review_state=calc_state
                )
            )

        return results

    def submit_review_decision(
        self,
        complaint_id: str,
        decision_in: ReviewDecisionCreate,
        reviewer: ReviewerIdentity
    ) -> ReviewDecision:
        complaint = self.db.query(Complaint).filter(
            or_(Complaint.id == complaint_id, Complaint.reference_id == complaint_id)
        ).first()

        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        # Map reviewer action to target complaint status
        action_status_map = {
            ReviewDecisionAction.APPROVE: ComplaintStatus.AUTHORITY_QUEUE,
            ReviewDecisionAction.REJECT: ComplaintStatus.REJECTED,
            ReviewDecisionAction.CONFIRM_REPAIR: ComplaintStatus.RESOLVED_AFTER_REVIEW,
            ReviewDecisionAction.REQUEST_REWORK: ComplaintStatus.REWORK_REQUESTED,
            ReviewDecisionAction.REQUEST_EVIDENCE: ComplaintStatus.EVIDENCE_REQUESTED,
        }

        if decision_in.action == ReviewDecisionAction.APPROVE:
            if complaint.status in (ComplaintStatus.VERIFICATION_PENDING, ComplaintStatus.REPAIR_CLAIMED, ComplaintStatus.DISPUTED):
                target_status = ComplaintStatus.RESOLVED_AFTER_REVIEW
            else:
                target_status = ComplaintStatus.AUTHORITY_QUEUE
        elif decision_in.action == ReviewDecisionAction.REJECT:
            if complaint.status in (ComplaintStatus.VERIFICATION_PENDING, ComplaintStatus.REPAIR_CLAIMED, ComplaintStatus.DISPUTED):
                target_status = ComplaintStatus.REWORK_REQUESTED
            else:
                target_status = ComplaintStatus.REJECTED
        else:
            target_status = action_status_map.get(decision_in.action)

        if not target_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported reviewer action: {decision_in.action}"
            )

        if decision_in.action == ReviewDecisionAction.REJECT:
            if not decision_in.reason or len(decision_in.reason.strip()) < 3:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A meaningful rejection reason (minimum 3 characters) is required when rejecting a complaint."
                )

        current_status = complaint.status
        allowed_transitions = VALID_TRANSITIONS.get(current_status, [])
        if target_status not in allowed_transitions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state transition: Cannot perform '{decision_in.action.value}' from current status '{current_status.value}'. Allowed transitions: {[s.value for s in allowed_transitions]}"
            )

        previous_status_val = complaint.status.value

        # Record official human decision
        review_decision = ReviewDecision(
            complaint_id=complaint.id,
            action=decision_in.action,
            previous_status=previous_status_val,
            new_status=target_status.value,
            reason=decision_in.reason,
            notes=decision_in.notes,
            reviewer_id=reviewer.reviewer_id,
            is_simulation=reviewer.is_simulated,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(review_decision)

        # Append immutable audit timeline event
        event_notes = f"Official Decision: {decision_in.action.value}. Reason: {decision_in.reason}"
        if decision_in.notes:
            event_notes += f" | Notes: {decision_in.notes}"

        status_event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=previous_status_val,
            new_status=target_status.value,
            actor_type=ActorType.REVIEWER,
            actor_id=reviewer.reviewer_id,
            notes=event_notes,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(status_event)

        # Update complaint status and department assignment on approval
        complaint.status = target_status
        complaint.updated_at = datetime.now(timezone.utc)

        if decision_in.action == ReviewDecisionAction.APPROVE:
            from app.services.incident_assessment_service import IncidentAssessmentService
            domain, dept = IncidentAssessmentService._determine_domain_and_department(complaint)
            complaint.service_domain = domain
            complaint.assigned_department = dept
            complaint.assignment_status = "ASSIGNED"

            assignment_entry = ComplaintAssignment(
                complaint_id=complaint.id,
                service_domain=domain,
                department=dept,
                assignment_status="ASSIGNED",
                assigned_by=reviewer.reviewer_id,
                notes=f"Reviewer Approval: {decision_in.reason}",
                created_at=datetime.now(timezone.utc)
            )
            self.db.add(assignment_entry)

        # Commit before notifications
        self.db.commit()
        self.db.refresh(review_decision)
        self.db.refresh(complaint)

        # Trigger notification to citizen
        try:
            notif_service = NotificationService(self.db)
            notif_service.notify_status_change(complaint, target_status)
        except Exception:
            pass

        return review_decision

    def list_review_decisions(self, complaint_id: str) -> List[ReviewDecision]:
        complaint = self.db.query(Complaint).filter(
            or_(Complaint.id == complaint_id, Complaint.reference_id == complaint_id)
        ).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        return self.db.query(ReviewDecision).filter(
            ReviewDecision.complaint_id == complaint.id
        ).order_by(ReviewDecision.created_at.desc()).all()

    def submit_citizen_dispute(
        self,
        complaint_id: str,
        dispute_in: DisputeCreate,
        citizen_id: str
    ) -> ComplaintDispute:
        complaint = self.db.query(Complaint).filter(
            or_(Complaint.id == complaint_id, Complaint.reference_id == complaint_id)
        ).first()

        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        # Ownership validation: only reporting citizen or guest citizen matching can dispute
        if complaint.citizen_id and complaint.citizen_id != "guest_citizen":
            if citizen_id != complaint.citizen_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Citizen authorization failure: Only the original reporting citizen can dispute this complaint resolution."
                )

        # Check for duplicate active pending dispute
        active_dispute = self.db.query(ComplaintDispute).filter(
            ComplaintDispute.complaint_id == complaint.id,
            ComplaintDispute.status == DisputeStatus.PENDING_REVIEW
        ).first()
        if active_dispute or complaint.status == ComplaintStatus.DISPUTED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A dispute is already pending review for this complaint."
            )

        # State validation: disputes only permitted when complaint was resolved
        if complaint.status != ComplaintStatus.RESOLVED_AFTER_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot dispute complaint in status '{complaint.status.value}'. Disputes can only be filed against 'RESOLVED_AFTER_REVIEW' complaints."
            )

        # Optional supporting evidence check
        if dispute_in.supporting_evidence_id:
            evidence = self.db.query(ComplaintEvidence).filter(
                ComplaintEvidence.id == dispute_in.supporting_evidence_id,
                ComplaintEvidence.complaint_id == complaint.id
            ).first()
            if not evidence:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Supporting evidence '{dispute_in.supporting_evidence_id}' does not belong to this complaint."
                )

        previous_status_val = complaint.status.value

        # Create dispute record
        dispute = ComplaintDispute(
            complaint_id=complaint.id,
            citizen_id=citizen_id,
            reason=dispute_in.reason,
            supporting_evidence_id=dispute_in.supporting_evidence_id,
            status=DisputeStatus.PENDING_REVIEW,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(dispute)

        # Transition status to DISPUTED
        complaint.status = ComplaintStatus.DISPUTED
        complaint.updated_at = datetime.now(timezone.utc)

        # Timeline audit entry
        status_event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=previous_status_val,
            new_status=ComplaintStatus.DISPUTED.value,
            actor_type=ActorType.CITIZEN,
            actor_id=citizen_id,
            notes=f"Citizen Dispute Filed: {dispute_in.reason}",
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(status_event)

        self.db.commit()
        self.db.refresh(dispute)
        self.db.refresh(complaint)

        # In-app notification
        try:
            notif_service = NotificationService(self.db)
            notif_service.notify_status_change(complaint, ComplaintStatus.DISPUTED)
        except Exception:
            pass

        return dispute

    def list_complaint_disputes(self, complaint_id: str) -> List[ComplaintDispute]:
        complaint = self.db.query(Complaint).filter(
            or_(Complaint.id == complaint_id, Complaint.reference_id == complaint_id)
        ).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        return self.db.query(ComplaintDispute).filter(
            ComplaintDispute.complaint_id == complaint.id
        ).order_by(ComplaintDispute.created_at.desc()).all()

    def list_all_pending_disputes(self, skip: int = 0, limit: int = 50) -> List[ComplaintDispute]:
        return self.db.query(ComplaintDispute).filter(
            ComplaintDispute.status == DisputeStatus.PENDING_REVIEW
        ).order_by(ComplaintDispute.created_at.desc()).offset(skip).limit(limit).all()

    def resolve_dispute(
        self,
        complaint_id: str,
        dispute_id: str,
        resolve_in: DisputeResolve,
        reviewer: ReviewerIdentity
    ) -> ComplaintDispute:
        complaint = self.db.query(Complaint).filter(
            or_(Complaint.id == complaint_id, Complaint.reference_id == complaint_id)
        ).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        dispute = self.db.query(ComplaintDispute).filter(
            ComplaintDispute.id == dispute_id,
            ComplaintDispute.complaint_id == complaint.id
        ).first()
        if not dispute:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dispute '{dispute_id}' not found for complaint '{complaint_id}'"
            )

        if dispute.status != DisputeStatus.PENDING_REVIEW:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dispute has already been resolved with outcome '{dispute.status.value}'."
            )

        # Update dispute
        dispute.status = resolve_in.outcome
        dispute.reviewer_id = reviewer.reviewer_id
        dispute.reviewer_notes = resolve_in.reviewer_notes
        dispute.resolved_at = datetime.now(timezone.utc)

        previous_status_val = complaint.status.value

        # Determine new complaint status
        if resolve_in.outcome == DisputeStatus.UPHELD:
            # Citizen dispute was justified - order rework
            target_status = ComplaintStatus.REWORK_REQUESTED
            outcome_text = "Dispute UPHELD: Repair inadequate, rework ordered."
        else:
            # Resolution is confirmed - reassessment completed
            target_status = ComplaintStatus.REASSESSMENT_COMPLETED
            outcome_text = "Dispute OVERTURNED: Resolution verified and affirmed."

        complaint.status = target_status
        complaint.updated_at = datetime.now(timezone.utc)

        # Append timeline audit event
        status_event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=previous_status_val,
            new_status=target_status.value,
            actor_type=ActorType.REVIEWER,
            actor_id=reviewer.reviewer_id,
            notes=f"{outcome_text} Reviewer Notes: {resolve_in.reviewer_notes}",
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(status_event)

        self.db.commit()
        self.db.refresh(dispute)
        self.db.refresh(complaint)

        # Send notification to citizen
        try:
            notif_service = NotificationService(self.db)
            if complaint.citizen_id:
                notif_service.repo.create(
                    user_id=complaint.citizen_id,
                    title="Dispute Review Completed",
                    message=f"[{complaint.reference_id}] Dispute outcome: {resolve_in.outcome.value}. {resolve_in.reviewer_notes}",
                    notification_type=NotificationType.STATUS_UPDATE,
                    complaint_id=complaint.id
                )
        except Exception:
            pass

        return dispute
