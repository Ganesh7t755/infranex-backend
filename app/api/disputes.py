from typing import List
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_citizen_id
from app.schemas.dispute import (
    DisputeCreate,
    DisputeResponse,
)
from app.services.reviewer_service import ReviewerService

router = APIRouter(prefix="/api/complaints/{complaint_id}/disputes", tags=["Citizen Disputes"])

@router.post(
    "",
    response_model=DisputeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a citizen dispute for a resolved complaint"
)
def submit_dispute(
    complaint_id: str,
    dispute_in: DisputeCreate,
    citizen_id: str = Depends(get_current_citizen_id),
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.submit_citizen_dispute(
        complaint_id=complaint_id,
        dispute_in=dispute_in,
        citizen_id=citizen_id
    )

@router.get(
    "",
    response_model=List[DisputeResponse],
    summary="List dispute records for a complaint"
)
def list_disputes(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.list_complaint_disputes(complaint_id=complaint_id)
