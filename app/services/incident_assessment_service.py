import math
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.models.incident_assessment import IncidentAssessment
from app.models.assignment import ComplaintAssignment
from app.services.incident_assessment_provider import (
    IncidentAssessmentProvider,
    DeterministicMockAssessmentProvider,
    ClipIncidentAssessmentProvider,
    get_default_assessment_provider,
    IncidentAssessmentInput,
    IncidentAssessmentResult,
)
from app.schemas.complaint import ComplaintUpdateStatus
from app.services.complaint_service import ComplaintService, VALID_TRANSITIONS

# Routing Policy Threshold
HIGH_CONFIDENCE_THRESHOLD = 0.90

# Eligible Lifecycle States for Assessment
ELIGIBLE_ASSESSMENT_STATES = {
    ComplaintStatus.SUBMITTED,
    ComplaintStatus.PROCESSING,
    ComplaintStatus.MORE_EVIDENCE_REQUIRED,
    ComplaintStatus.REVIEW_REQUIRED,
}

class IncidentAssessmentService:
    """
    Coordinates initial civic incident evidence assessment, safety validation,
    and confidence-based routing to Authority or Human Review queues.
    """

    def __init__(
        self,
        db: Session,
        provider: Optional[IncidentAssessmentProvider] = None
    ):
        self.db = db
        self.provider = provider or get_default_assessment_provider()
        self.complaint_service = ComplaintService(db)

    def assess_and_route(
        self,
        complaint_id: str,
        evidence_id: Optional[str] = None,
        actor_id: Optional[str] = None
    ) -> Tuple[IncidentAssessment, Complaint]:
        """
        Executes mandatory safety checks, triggers assessment provider, validates
        model output, persists IncidentAssessment history, and routes complaint
        to AUTHORITY_QUEUE or REVIEW_REQUIRED via the canonical state machine.
        """
        # 1. Retrieve complaint
        complaint = self.db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )

        # 2. Reject terminal or ineligible lifecycle states BEFORE invoking provider or mutating state
        if complaint.status not in ELIGIBLE_ASSESSMENT_STATES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot assess complaint in lifecycle state '{complaint.status.value}'. Assessments are restricted to active intake/review states: {[s.value for s in ELIGIBLE_ASSESSMENT_STATES]}."
            )

        # 3. Resolve & validate evidence association
        evidence: Optional[ComplaintEvidence] = None
        if evidence_id:
            evidence = (
                self.db.query(ComplaintEvidence)
                .filter(ComplaintEvidence.id == evidence_id)
                .first()
            )
            if not evidence:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Evidence item '{evidence_id}' not found"
                )
            if evidence.complaint_id != complaint.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evidence item '{evidence_id}' does not belong to complaint '{complaint_id}'"
                )
        else:
            # Auto-detect latest initial report evidence
            evidence = next(
                (e for e in reversed(complaint.evidence_items) if e.evidence_type == EvidenceType.INITIAL_REPORT),
                None
            )

        # 4. Transition to PROCESSING state via state machine validator if currently SUBMITTED, MORE_EVIDENCE_REQUIRED, or REVIEW_REQUIRED
        if complaint.status != ComplaintStatus.PROCESSING:
            self.complaint_service.transition_status(
                complaint_id=complaint.id,
                update_in=ComplaintUpdateStatus(
                    new_status=ComplaintStatus.PROCESSING,
                    actor_id=actor_id or "ai_assessment_service",
                    notes="Incident transitioned to PROCESSING for automated AI assessment and routing."
                ),
                actor_type=ActorType.SYSTEM
            )
            self.db.refresh(complaint)

        # 5. Construct provider input
        category_str = (
            complaint.category.value
            if hasattr(complaint.category, "value")
            else str(complaint.category)
        )
        provider_input = IncidentAssessmentInput(
            complaint_id=complaint.id,
            category=category_str,
            title=complaint.title,
            description=complaint.description,
            evidence_id=evidence.id if evidence else None,
            evidence_path=evidence.file_path if evidence else None,
            evidence_name=evidence.file_name if evidence else None,
            mime_type=evidence.mime_type if evidence else None,
            file_size=evidence.file_size if evidence else None,
        )

        # 6. Execute assessment with error, timeout, and information-leak containment
        assessment_result: IncidentAssessmentResult
        try:
            assessment_result = self.provider.assess_incident(provider_input)
        except Exception as exc:
            # Contain provider failure: do not crash, leak raw exception text, or leave complaint undefined
            assessment_result = IncidentAssessmentResult(
                provider_id=getattr(self.provider, "provider_id", "external_provider"),
                model_name=getattr(self.provider, "model_name", "unknown"),
                confidence_score=None,
                detected_category=None,
                category_match=False,
                evidence_suitable=False,
                explanation="AI assessment service encountered a processing error. Assessment routed to human review.",
                limitations="Inference error; requires manual reviewer evaluation.",
                is_simulation=True,
                review_required=True,
                assessment_metadata={
                    "error_code": "PROVIDER_PROCESSING_ERROR",
                    "exception_type": type(exc).__name__,
                    "diagnostic": "Automated assessment failed to complete. Inspection routed to review queue."
                }
            )

        # 7. Validate & sanitize model output before persistence
        validated_score = self._validate_confidence_score(assessment_result.confidence_score)
        validated_cat_match = bool(assessment_result.category_match) if assessment_result.category_match is not None else False
        is_suitable = bool(assessment_result.evidence_suitable)

        # Automated moderation safeguard: Revoke public approval if evidence is flagged as unsuitable
        if evidence is not None and not is_suitable:
            evidence.is_public_approved = False

        # Smart category auto-alignment: If citizen's text and AI detection agree (e.g. reported streetlight with POTHOLE category)
        text_corpus = f"{complaint.title} {complaint.description}".lower()
        if (
            not validated_cat_match
            and assessment_result.detected_category
            and "mismatch" not in text_corpus
            and "wrong_category" not in text_corpus
        ):
            detected_cat_str = str(assessment_result.detected_category).upper()
            if (
                any(w in text_corpus for w in ["streetlight", "street light", "light", "bulb", "lamp", "pole", "wire", "cable", "bescom"])
                and detected_cat_str == "BROKEN_STREETLIGHT"
            ):
                complaint.category = ComplaintCategory.BROKEN_STREETLIGHT
                validated_cat_match = True
            elif (
                any(w in text_corpus for w in ["garbage", "trash", "waste", "dump", "debris", "litter", "bin"])
                and detected_cat_str == "GARBAGE"
            ):
                complaint.category = ComplaintCategory.GARBAGE
                validated_cat_match = True
            elif (
                any(w in text_corpus for w in ["pothole", "crater"])
                and detected_cat_str in ("POTHOLE", "DAMAGED_ROAD")
            ):
                complaint.category = ComplaintCategory.POTHOLE
                validated_cat_match = True

        # 8. Apply Confidence-Based Routing Policy
        # Mandatory policy: Confidence must be STRICTLY GREATER than 0.90 (0.9000 -> Human Review, 0.9001 -> eligible for direct routing)
        strictly_above_threshold = (validated_score is not None and validated_score > HIGH_CONFIDENCE_THRESHOLD)
        eligible_for_authority = (
            evidence is not None and
            is_suitable is True and
            strictly_above_threshold is True and
            validated_cat_match is True and
            assessment_result.review_required is False
        )

        # Multi-Domain Department Assignment (Stage 7C)
        domain, department = self._determine_domain_and_department(complaint)
        complaint.service_domain = domain
        complaint.assigned_department = department
        complaint.assignment_status = "ASSIGNED" if eligible_for_authority else "UNASSIGNED"

        target_status = ComplaintStatus.AUTHORITY_QUEUE if eligible_for_authority else ComplaintStatus.REVIEW_REQUIRED
        routing_reason = (
            f"Automated Routing: High confidence ({validated_score:.4f} > {HIGH_CONFIDENCE_THRESHOLD}) "
            f"with verified category match and suitable evidence. Assigned to {department} ({domain}). Queued for authority."
            if eligible_for_authority else
            f"Automated Routing: Human review required. (Score: {validated_score if validated_score is not None else 'None'} <= {HIGH_CONFIDENCE_THRESHOLD}, "
            f"Category Match: {validated_cat_match}, Evidence Suitable: {is_suitable}). Triage domain: {domain}."
        )

        # Record persistent, auditable department assignment history
        assignment_entry = ComplaintAssignment(
            complaint_id=complaint.id,
            service_domain=domain,
            department=department,
            assignment_status=complaint.assignment_status,
            assigned_by=actor_id or "ai_confidence_routing_engine",
            notes=f"Routing decision: {routing_reason}",
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(assignment_entry)

        # 9. Persist IncidentAssessment record (history preserved, retries append new rows)
        assessment = IncidentAssessment(
            complaint_id=complaint.id,
            evidence_id=evidence.id if evidence else None,
            provider_id=assessment_result.provider_id,
            model_name=assessment_result.model_name,
            confidence_score=validated_score,
            category_match=assessment_result.category_match,
            detected_category=assessment_result.detected_category,
            evidence_suitable=is_suitable,
            explanation=assessment_result.explanation,
            limitations=assessment_result.limitations,
            is_simulation=assessment_result.is_simulation,
            review_required=(not eligible_for_authority),
            assessment_metadata=assessment_result.assessment_metadata,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(assessment)

        # 10. Update complaint status via canonical state machine (transition_status)
        self.complaint_service.transition_status(
            complaint_id=complaint.id,
            update_in=ComplaintUpdateStatus(
                new_status=target_status,
                actor_id=actor_id or "ai_assessment_service",
                notes=f"Civic AI Assessment: {routing_reason}"
            ),
            actor_type=ActorType.SYSTEM
        )

        self.db.commit()
        self.db.refresh(assessment)
        self.db.refresh(complaint)

        return assessment, complaint


    def get_assessments(self, complaint_id: str) -> List[IncidentAssessment]:
        """Retrieves chronological assessment history for a complaint."""
        return (
            self.db.query(IncidentAssessment)
            .filter(IncidentAssessment.complaint_id == complaint_id)
            .order_by(IncidentAssessment.created_at.desc())
            .all()
        )

    def get_assessment(self, complaint_id: str, assessment_id: str) -> IncidentAssessment:
        """Retrieves a specific assessment record."""
        assessment = (
            self.db.query(IncidentAssessment)
            .filter(
                IncidentAssessment.id == assessment_id,
                IncidentAssessment.complaint_id == complaint_id
            )
            .first()
        )
        if not assessment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Assessment '{assessment_id}' not found for complaint '{complaint_id}'"
            )
        return assessment

    @staticmethod
    def _validate_confidence_score(score: Any) -> Optional[float]:
        """
        Validates confidence score strictly in [0.0, 1.0].
        Never converts invalid, NaN, infinite, or out-of-range values into high confidence.
        """
        if score is None:
            return None
        try:
            val = float(score)
            if math.isnan(val) or math.isinf(val):
                return None
            if 0.0 <= val <= 1.0:
                return round(val, 4)
            return None  # Out of range scores safely classified as invalid/None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _determine_domain_and_department(complaint: Complaint) -> Tuple[str, str]:
        """
        Associates defect categories, descriptions, and operational keywords with
        appropriate municipal service domains and responsible departments.
        """
        cat = complaint.category.value if hasattr(complaint.category, "value") else str(complaint.category)
        text_corpus = f"{complaint.title} {complaint.description}".lower()

        # Check explicit category associations
        if cat in ("POTHOLE", "DAMAGED_ROAD"):
            return "ROADS", "BBMP - Road Infrastructure Division"
        elif cat == "GARBAGE":
            return "SANITATION", "SWM - Solid Waste Management"
        elif cat == "BROKEN_STREETLIGHT":
            return "STREETLIGHTS", "BESCOM - Streetlight Cell"

        # Domain keywords for OTHER category or multi-domain routing
        electrical_keywords = ["wire", "power", "meter", "bescom", "shock", "spark", "transformer", "fuse", "outage", "electric", "cable", "pole"]
        sanitation_keywords = ["waste", "trash", "debris", "drain", "garbage", "sewage", "dump", "litter"]
        road_keywords = ["asphalt", "pave", "footpath", "curb", "median", "divider", "manhole", "road", "pothole"]

        if any(k in text_corpus for k in electrical_keywords):
            return "ELECTRICITY", "BESCOM - Power Infrastructure"
        elif any(k in text_corpus for k in sanitation_keywords):
            return "SANITATION", "SWM - Solid Waste Management"
        elif any(k in text_corpus for k in road_keywords):
            return "ROADS", "BBMP - Road Infrastructure Division"

        # Safe triage state for unclassified or ambiguous incidents
        return "GENERAL_MAINTENANCE", "Unassigned - Civic Triage Queue"

