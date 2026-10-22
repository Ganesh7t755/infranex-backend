from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.repair_verification import (
    RepairVerificationRequest,
    RepairVerificationResponse,
)
from app.services.repair_verification_service import RepairVerificationService

router = APIRouter(prefix="/api/complaints/{complaint_id}/verifications", tags=["Repair Verification"])

@router.post(
    "",
    response_model=RepairVerificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request an AI-assisted civic repair verification assessment"
)
def request_repair_verification(
    complaint_id: str,
    request_in: Optional[RepairVerificationRequest] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    db: Session = Depends(get_db)
):
    service = RepairVerificationService(db)
    before_id = request_in.before_evidence_id if request_in else None
    after_id = request_in.after_evidence_id if request_in else None
    actor = x_user_id or "reviewer_demo"
    verification = service.request_verification(
        complaint_id=complaint_id,
        before_evidence_id=before_id,
        after_evidence_id=after_id,
        actor_id=actor
    )
    return verification

@router.get(
    "",
    response_model=List[RepairVerificationResponse],
    summary="List verification assessment history for a complaint"
)
def list_repair_verifications(
    complaint_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db)
):
    service = RepairVerificationService(db)
    return service.list_verifications(complaint_id=complaint_id, skip=skip, limit=limit)

@router.get(
    "/{verification_id}",
    response_model=RepairVerificationResponse,
    summary="Get a specific repair verification assessment"
)
def get_repair_verification(
    complaint_id: str,
    verification_id: str,
    db: Session = Depends(get_db)
):
    service = RepairVerificationService(db)
    return service.get_verification(complaint_id=complaint_id, verification_id=verification_id)
