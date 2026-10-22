from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.schemas.incident_assessment import IncidentAssessmentResponse
from app.services.complaint_service import ComplaintService
from app.services.incident_assessment_service import IncidentAssessmentService

router = APIRouter(prefix="/api/complaints/{complaint_id}/assessments", tags=["AI Incident Assessment"])


def verify_assessment_access(
    complaint_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_reviewer_token: Optional[str] = Header(None, alias="X-Reviewer-Token"),
    x_reviewer_id: Optional[str] = Header(None, alias="X-Reviewer-ID"),
    db: Session = Depends(get_db)
) -> str:
    """
    Enforces authorization boundary for incident assessment operations.

    Rules:
    1. Anonymous access is strictly denied (401 Unauthorized).
    2. In production, header-based simulated identity is prohibited (403 Forbidden).
    3. Reviewer role access requires legitimate reviewer credentials (X-Role: REVIEWER or valid X-Reviewer-Token).
    4. Citizen access strictly enforces complaint ownership: X-User-ID must match complaint.citizen_id.
    5. Callers attempting to access another citizen's complaint without reviewer credentials are denied (403 Forbidden).
    6. Non-existent complaints return 404 Not Found.
    """
    clean_user = (x_user_id or "").strip()
    clean_role = (x_role or "").strip()
    clean_rev_token = (x_reviewer_token or "").strip()

    # Rule 1: Deny anonymous access
    if not clean_user and not clean_role and not clean_rev_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide valid credentials."
        )

    # Rule 2: In production, header-based identity assertions are not trusted
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Header-based authentication is disabled in production. Verified cryptographic credentials required."
        )

    # Rule 3: Check reviewer credentials
    valid_token = getattr(settings, "DEV_REVIEWER_TOKEN", "infranex-dev-reviewer-secret-key-stage5")
    is_reviewer = (clean_role == "REVIEWER") or (bool(clean_rev_token) and clean_rev_token == valid_token)

    # Rule 4 & 5: Complaint lookup and access control
    complaint_service = ComplaintService(db)
    complaint = complaint_service.get_complaint(complaint_id)
    # Note: get_complaint raises 404 HTTPException if complaint not found

    if is_reviewer:
        # Legitimate reviewer access
        actor = (x_reviewer_id or "").strip() or clean_user or "authorized_reviewer"
        return actor

    if clean_user and clean_user == complaint.citizen_id:
        # Verified complaint owner access
        return clean_user

    # Neither authorized reviewer nor complaint owner
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: You do not have permission to access assessments for this complaint."
    )


@router.post(
    "",
    response_model=IncidentAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger automated AI assessment and confidence-based routing for an incident"
)
def assess_and_route_incident(
    complaint_id: str,
    evidence_id: Optional[str] = Query(None, description="Optional specific evidence ID to assess"),
    actor_id: str = Depends(verify_assessment_access),
    db: Session = Depends(get_db)
):
    service = IncidentAssessmentService(db)
    assessment, _ = service.assess_and_route(
        complaint_id=complaint_id,
        evidence_id=evidence_id,
        actor_id=actor_id
    )
    return assessment


@router.get(
    "",
    response_model=List[IncidentAssessmentResponse],
    summary="List chronological assessment history for an incident"
)
def list_incident_assessments(
    complaint_id: str,
    actor_id: str = Depends(verify_assessment_access),
    db: Session = Depends(get_db)
):
    service = IncidentAssessmentService(db)
    return service.get_assessments(complaint_id=complaint_id)


@router.get(
    "/{assessment_id}",
    response_model=IncidentAssessmentResponse,
    summary="Get a specific incident assessment record"
)
def get_incident_assessment(
    complaint_id: str,
    assessment_id: str,
    actor_id: str = Depends(verify_assessment_access),
    db: Session = Depends(get_db)
):
    service = IncidentAssessmentService(db)
    return service.get_assessment(complaint_id=complaint_id, assessment_id=assessment_id)
