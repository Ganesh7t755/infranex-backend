import os
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.models.evidence import EvidenceType
from app.schemas.complaint import (
    ComplaintCreate,
    ComplaintDetailResponse,
    ComplaintSummaryResponse,
    ComplaintUpdateStatus,
)
from app.schemas.evidence import EvidenceResponse
from app.schemas.status_event import StatusEventResponse
from app.schemas.reviewer import ReviewDecisionResponse
from app.services.complaint_service import ComplaintService
from app.services.reviewer_service import ReviewerService
from app.storage.file_storage import storage

router = APIRouter(prefix="/api/complaints", tags=["Complaints"])

@router.post(
    "",
    response_model=ComplaintDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new civic complaint"
)
def create_complaint(
    complaint_in: ComplaintCreate,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    complaint = service.create_complaint(complaint_in)
    return complaint

@router.get(
    "",
    response_model=List[ComplaintSummaryResponse],
    summary="List civic complaints with optional filters"
)
def list_complaints(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    category: Optional[ComplaintCategory] = Query(None, description="Filter by defect category"),
    status: Optional[ComplaintStatus] = Query(None, description="Filter by current status"),
    citizen_id: Optional[str] = Query(None, description="Filter by citizen identifier"),
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    complaints = service.list_complaints(
        skip=skip,
        limit=limit,
        category=category,
        status_filter=status,
        citizen_id=citizen_id
    )
    
    # Map to summary response
    summaries = []
    for c in complaints:
        latest_event = c.status_events[-1].notes if c.status_events else None
        summaries.append(
            ComplaintSummaryResponse(
                id=c.id,
                reference_id=c.reference_id,
                title=c.title,
                category=c.category,
                status=c.status,
                location_address=c.location_address,
                latitude=c.latitude,
                longitude=c.longitude,
                location_type=c.location_type,
                citizen_id=c.citizen_id,
                created_at=c.created_at,
                updated_at=c.updated_at,
                evidence_count=len(c.evidence_items),
                latest_update=latest_event
            )
        )
    return summaries

@router.get(
    "/{complaint_id}",
    response_model=ComplaintDetailResponse,
    summary="Get full details for a complaint by ID or Reference"
)
def get_complaint(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    return service.get_complaint(complaint_id)

@router.get(
    "/{complaint_id}/timeline",
    response_model=List[StatusEventResponse],
    summary="Get chronological timeline and audit trail for a complaint"
)
def get_complaint_timeline(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    return service.get_timeline(complaint_id)

@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintDetailResponse,
    summary="Transition complaint status with state-machine validation"
)
def update_complaint_status(
    complaint_id: str,
    update_in: ComplaintUpdateStatus,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    return service.transition_status(complaint_id, update_in)

@router.post(
    "/{complaint_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and attach photo evidence to a complaint"
)
def upload_evidence(
    complaint_id: str,
    file: UploadFile = File(...),
    evidence_type: EvidenceType = Form(EvidenceType.INITIAL_REPORT),
    is_public_approved: Optional[bool] = Form(None),
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    return service.attach_evidence_file(
        complaint_id=complaint_id,
        file=file,
        evidence_type=evidence_type,
        is_public_approved=is_public_approved
    )

@router.get(
    "/{complaint_id}/evidence/{evidence_id}/file",
    summary="Retrieve an attached evidence file securely"
)
def get_evidence_file(
    complaint_id: str,
    evidence_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    complaint = service.get_complaint(complaint_id)
    evidence = next((e for e in complaint.evidence_items if e.id == evidence_id), None)
    resolved_path = storage.resolve_path(evidence.file_path) if evidence else None
    if not evidence or not resolved_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence file not found")
    return FileResponse(resolved_path, media_type=evidence.mime_type, filename=evidence.file_name)

@router.patch(
    "/{complaint_id}/evidence/{evidence_id}/moderation",
    response_model=EvidenceResponse,
    summary="Approve or revoke public visibility of an attached evidence item"
)
def moderate_evidence(
    complaint_id: str,
    evidence_id: str,
    moderation_in: dict,
    db: Session = Depends(get_db)
):
    is_approved = moderation_in.get("is_public_approved", False)
    service = ComplaintService(db)
    return service.moderate_evidence(complaint_id, evidence_id, is_approved)


@router.get(
    "/{complaint_id}/decisions",
    response_model=List[ReviewDecisionResponse],
    summary="List official review decisions for a complaint"
)
def get_complaint_decisions(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ReviewerService(db)
    return service.list_review_decisions(complaint_id=complaint_id)


@router.delete(
    "/{complaint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a complaint by ID or Reference"
)
def delete_complaint(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    service.delete_complaint(complaint_id)


