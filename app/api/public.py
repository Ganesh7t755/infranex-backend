import os
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.schemas.public_complaint import PublicComplaintSummary, PublicComplaintDetail
from app.services.complaint_service import ComplaintService
from app.storage.file_storage import storage

router = APIRouter(prefix="/api/public/complaints", tags=["Public Discovery"])

@router.get(
    "",
    response_model=List[PublicComplaintSummary],
    summary="Discover nearby public civic issues with optional location, radius, and filters"
)
def list_public_complaints(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    category: Optional[ComplaintCategory] = Query(None, description="Filter by defect category"),
    status: Optional[ComplaintStatus] = Query(None, description="Filter by current status"),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="User latitude for distance calculation"),
    lng: Optional[float] = Query(None, ge=-180.0, le=180.0, description="User longitude for distance calculation"),
    radius_km: Optional[float] = Query(None, gt=0, le=100.0, description="Discovery radius in kilometers"),
    sort_by: str = Query("recent", pattern="^(recent|distance)$", description="Sort order: 'recent' or 'distance'"),
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    items = service.list_public_complaints(
        skip=skip,
        limit=limit,
        category=category,
        status_filter=status,
        user_lat=lat,
        user_lng=lng,
        radius_km=radius_km,
        sort_by=sort_by
    )
    return [PublicComplaintSummary.model_validate(item) for item in items]

@router.get(
    "/{complaint_id}",
    response_model=PublicComplaintDetail,
    summary="Get sanitized public details for a civic complaint"
)
def get_public_complaint(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    detail = service.get_public_complaint(complaint_id)
    return PublicComplaintDetail.model_validate(detail)

@router.get(
    "/{complaint_id}/evidence/{evidence_id}/file",
    summary="Retrieve publicly approved evidence image file"
)
def get_public_evidence_file(
    complaint_id: str,
    evidence_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    evidence = service.get_public_evidence(complaint_id, evidence_id)
    resolved_path = storage.resolve_path(evidence.file_path) if evidence else None
    if resolved_path and os.path.exists(resolved_path):
        return FileResponse(resolved_path, media_type=evidence.mime_type, filename=evidence.file_name)

    stream = storage.get_stream(evidence.file_path) if evidence else None
    if stream:
        return StreamingResponse(
            stream,
            media_type=evidence.mime_type,
            headers={"Content-Disposition": f'inline; filename="{evidence.file_name}"'}
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Evidence file not found on disk"
    )


@router.delete(
    "/{complaint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a public complaint by ID or Reference"
)
def delete_public_complaint(
    complaint_id: str,
    db: Session = Depends(get_db)
):
    service = ComplaintService(db)
    service.delete_complaint(complaint_id)

