from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_reviewer, ReviewerIdentity
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.schemas.reviewer import (
    ReviewDecisionCreate,
    ReviewDecisionResponse,
    ReviewQueueItemResponse,
)
from app.schemas.dispute import (
    DisputeResolve,
    DisputeResponse,
)
from app.services.reviewer_service import ReviewerService

router = APIRouter(prefix="/api/reviewer", tags=["Authorized Reviewer Workflow"])

@router.get(
    "/queue",
    response_model=List[ReviewQueueItemResponse],
    summary="Get queue of complaints requiring human reviewer attention"
)
def get_review_queue(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    category: Optional[ComplaintCategory] = Query(None, description="Filter defect category"),
    status: Optional[ComplaintStatus] = Query(None, description="Filter complaint status"),
    review_state: Optional[str] = Query(None, description="Filter review state: NEEDS_REVIEW, PENDING_VERIFICATION, DISPUTED, REWORK, RESOLVED"),
    reviewer: ReviewerIdentity = Depends(get_current_reviewer),
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.get_review_queue(
        skip=skip,
        limit=limit,
        category=category,
        status_filter=status,
        review_state=review_state
    )

@router.post(
    "/complaints/{complaint_id}/decide",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an official human reviewer decision"
)
def submit_review_decision(
    complaint_id: str,
    decision_in: ReviewDecisionCreate,
    reviewer: ReviewerIdentity = Depends(get_current_reviewer),
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.submit_review_decision(
        complaint_id=complaint_id,
        decision_in=decision_in,
        reviewer=reviewer
    )

@router.get(
    "/complaints/{complaint_id}/decisions",
    response_model=List[ReviewDecisionResponse],
    summary="List official review decisions for a complaint"
)
def list_review_decisions(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.list_review_decisions(complaint_id=complaint_id)

@router.get(
    "/disputes",
    response_model=List[DisputeResponse],
    summary="List all citizen disputes pending reviewer action"
)
def list_pending_disputes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    reviewer: ReviewerIdentity = Depends(get_current_reviewer),
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.list_all_pending_disputes(skip=skip, limit=limit)

@router.post(
    "/complaints/{complaint_id}/disputes/{dispute_id}/resolve",
    response_model=DisputeResponse,
    summary="Resolve a citizen dispute (uphold or overturn)"
)
def resolve_dispute(
    complaint_id: str,
    dispute_id: str,
    resolve_in: DisputeResolve,
    reviewer: ReviewerIdentity = Depends(get_current_reviewer),
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.resolve_dispute(
        complaint_id=complaint_id,
        dispute_id=dispute_id,
        resolve_in=resolve_in,
        reviewer=reviewer
    )
