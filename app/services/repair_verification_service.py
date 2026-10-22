from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.complaint import Complaint
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.models.repair_verification import RepairVerification
from app.services.verification_provider import (
    RepairVerificationProvider,
    MockRepairVerificationProvider,
    VerificationInput,
)

class RepairVerificationService:
    def __init__(
        self,
        db: Session,
        provider: Optional[RepairVerificationProvider] = None
    ):
        self.db = db
        self.provider = provider or MockRepairVerificationProvider()

    def request_verification(
        self,
        complaint_id: str,
        before_evidence_id: Optional[str] = None,
        after_evidence_id: Optional[str] = None,
        actor_id: Optional[str] = None
    ) -> RepairVerification:
        # 1. Identify valid complaint
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        # 2. Resolve & validate before evidence
        before_evidence: Optional[ComplaintEvidence] = None
        if before_evidence_id:
            before_evidence = (
                self.db.query(ComplaintEvidence)
                .filter(ComplaintEvidence.id == before_evidence_id)
                .first()
            )
            if not before_evidence:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Before evidence item '{before_evidence_id}' not found"
                )
            if before_evidence.complaint_id != complaint.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evidence item '{before_evidence_id}' does not belong to complaint '{complaint_id}'"
                )
        else:
            # Auto-detect latest initial report evidence
            before_evidence = next(
                (e for e in reversed(complaint.evidence_items) if e.evidence_type == EvidenceType.INITIAL_REPORT),
                None
            )

        # 3. Resolve & validate after evidence
        after_evidence: Optional[ComplaintEvidence] = None
        if after_evidence_id:
            after_evidence = (
                self.db.query(ComplaintEvidence)
                .filter(ComplaintEvidence.id == after_evidence_id)
                .first()
            )
            if not after_evidence:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"After evidence item '{after_evidence_id}' not found"
                )
            if after_evidence.complaint_id != complaint.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evidence item '{after_evidence_id}' does not belong to complaint '{complaint_id}'"
                )
        else:
            # Auto-detect latest repair claim evidence (or distinct subsequent evidence)
            after_evidence = next(
                (e for e in reversed(complaint.evidence_items) if e.evidence_type == EvidenceType.REPAIR_CLAIM),
                None
            )
            # If no tagged REPAIR_CLAIM, use a second evidence item if available and distinct
            if not after_evidence and before_evidence and len(complaint.evidence_items) > 1:
                after_evidence = next(
                    (e for e in reversed(complaint.evidence_items) if e.id != before_evidence.id),
                    None
                )

        # 4. Check for duplicate recent verification (idempotency check within 30s)
        resolved_before_id = before_evidence.id if before_evidence else None
        resolved_after_id = after_evidence.id if after_evidence else None

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
        recent_verification = (
            self.db.query(RepairVerification)
            .filter(
                RepairVerification.complaint_id == complaint.id,
                RepairVerification.before_evidence_id == resolved_before_id,
                RepairVerification.after_evidence_id == resolved_after_id,
                RepairVerification.created_at >= cutoff
            )
            .first()
        )
        if recent_verification:
            return recent_verification

        # 5. Build provider input
        v_input = VerificationInput(
            complaint_id=complaint.id,
            category=complaint.category.value if hasattr(complaint.category, 'value') else str(complaint.category),
            title=complaint.title,
            description=complaint.description,
            before_evidence_path=before_evidence.file_path if before_evidence else None,
            before_evidence_name=before_evidence.file_name if before_evidence else None,
            after_evidence_path=after_evidence.file_path if after_evidence else None,
            after_evidence_name=after_evidence.file_name if after_evidence else None,
            before_mime_type=before_evidence.mime_type if before_evidence else None,
            after_mime_type=after_evidence.mime_type if after_evidence else None
        )

        # 6. Execute provider analysis
        result = self.provider.verify_repair(v_input)

        # 7. Persist verification record
        verification = RepairVerification(
            complaint_id=complaint.id,
            before_evidence_id=resolved_before_id,
            after_evidence_id=resolved_after_id,
            outcome=result.outcome,
            explanation=result.explanation,
            observations=result.observations,
            evidence_quality=result.evidence_quality,
            limitations=result.limitations,
            provider_id=result.provider_id,
            model_name=result.model_name,
            is_simulation=result.is_simulation,
            human_review_required=True,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(verification)

        # 8. Append audit/timeline event (WITHOUT changing official complaint status)
        audit_notes = (
            f"AI Repair Verification: {result.outcome.value}. "
            f"Advisory assessment; verification pending municipal review."
        )
        status_event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=complaint.status.value if hasattr(complaint.status, 'value') else str(complaint.status),
            new_status=complaint.status.value if hasattr(complaint.status, 'value') else str(complaint.status),
            actor_type=ActorType.SYSTEM,
            actor_id=actor_id or "ai_repair_verifier",
            notes=audit_notes,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(status_event)

        self.db.commit()
        self.db.refresh(verification)
        return verification

    def get_verification(self, complaint_id: str, verification_id: str) -> RepairVerification:
        verification = (
            self.db.query(RepairVerification)
            .filter(
                RepairVerification.id == verification_id,
                RepairVerification.complaint_id == complaint_id
            )
            .first()
        )
        if not verification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Verification '{verification_id}' not found for complaint '{complaint_id}'"
            )
        return verification

    def list_verifications(
        self,
        complaint_id: str,
        skip: int = 0,
        limit: int = 20
    ) -> List[RepairVerification]:
        # Validate complaint exists
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )
        return (
            self.db.query(RepairVerification)
            .filter(RepairVerification.complaint_id == complaint_id)
            .order_by(RepairVerification.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
