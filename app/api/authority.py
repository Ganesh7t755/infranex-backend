from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_authority, AuthorityIdentity
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.schemas.authority_action import (
    AuthorityActionCreate,
    AuthorityActionResponse,
    AuthorityAcknowledgeRequest,
    AuthorityDispatchRequest,
    AuthorityResolveRequest,
    AuthorityQueueItemResponse,
    AuthorityComplaintDetailResponse,
)
from app.services.authority_service import AuthorityService

router = APIRouter(prefix="/api/authority", tags=["Municipal Authority Workflow"])


@router.get(
    "/queue",
    response_model=List[AuthorityQueueItemResponse],
    summary="Get queue of complaints eligible for municipal authority action"
)
def get_authority_queue(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    category: Optional[ComplaintCategory] = Query(None, description="Filter defect category"),
    status: Optional[ComplaintStatus] = Query(None, description="Filter complaint status"),
    department: Optional[str] = Query(None, description="Filter by department"),
    domain: Optional[str] = Query(None, description="Filter by service domain"),
    assignment_status: Optional[str] = Query(None, description="Filter by assignment status"),
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.get_authority_queue(
        skip=skip,
        limit=limit,
        category=category,
        status_filter=status,
        department=department,
        domain=domain,
        assignment_status=assignment_status
    )


@router.get(
    "/complaints/{complaint_id}",
    response_model=AuthorityComplaintDetailResponse,
    summary="Get incident details for authorized municipal authority action"
)
def get_authority_complaint_detail(
    complaint_id: str,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.get_complaint_detail(complaint_id)


@router.post(
    "/complaints/{complaint_id}/actions",
    response_model=AuthorityActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an official authority action and transition complaint lifecycle"
)
def record_authority_action(
    complaint_id: str,
    action_in: AuthorityActionCreate,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.record_action(
        complaint_id=complaint_id,
        action_in=action_in,
        authority=authority
    )


@router.post(
    "/complaints/{complaint_id}/acknowledge",
    response_model=AuthorityActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Acknowledge and accept incident for work planning"
)
def acknowledge_complaint(
    complaint_id: str,
    req: Optional[AuthorityAcknowledgeRequest] = None,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.acknowledge_work(
        complaint_id=complaint_id,
        req=req or AuthorityAcknowledgeRequest(),
        authority=authority
    )


@router.post(
    "/complaints/{complaint_id}/dispatch",
    response_model=AuthorityActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Dispatch field crew or contractor with optional work order reference"
)
def dispatch_complaint(
    complaint_id: str,
    req: Optional[AuthorityDispatchRequest] = None,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.dispatch_work(
        complaint_id=complaint_id,
        req=req or AuthorityDispatchRequest(),
        authority=authority
    )


@router.post(
    "/complaints/{complaint_id}/resolve",
    response_model=AuthorityActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record incident repair or remediation resolution"
)
def resolve_complaint(
    complaint_id: str,
    req: AuthorityResolveRequest,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.resolve_work(
        complaint_id=complaint_id,
        req=req,
        authority=authority
    )


@router.get(
    "/complaints/{complaint_id}/actions",
    response_model=List[AuthorityActionResponse],
    summary="List chronological authority actions taken on a complaint"
)
def list_authority_actions(
    complaint_id: str,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.get_actions(complaint_id)


@router.get(
    "/complaints/{complaint_id}/actions/{action_id}",
    response_model=AuthorityActionResponse,
    summary="Get a specific authority action record"
)
def get_authority_action(
    complaint_id: str,
    action_id: str,
    authority: AuthorityIdentity = Depends(get_current_authority),
    db: Session = Depends(get_db)
):
    service = AuthorityService(db)
    return service.get_action(complaint_id, action_id)
