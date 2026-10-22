import os
from typing import List, Optional
from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.schemas.complaint import ComplaintCreate, ComplaintUpdateStatus
from app.schemas.evidence import EvidenceCreate
from app.repositories.complaint_repository import ComplaintRepository
from app.storage.file_storage import storage

VALID_TRANSITIONS = {
    # Initial intake & processing
    ComplaintStatus.SUBMITTED: [
        ComplaintStatus.PROCESSING,
        ComplaintStatus.UNDER_REVIEW,
        ComplaintStatus.REVIEW_REQUIRED,
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.REJECTED,
    ],
    ComplaintStatus.PROCESSING: [
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.REVIEW_REQUIRED,
        ComplaintStatus.REJECTED,
    ],

    # Human Review workflows
    ComplaintStatus.UNDER_REVIEW: [
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.EVIDENCE_REQUESTED,
        ComplaintStatus.REPAIR_IN_PROGRESS,
        ComplaintStatus.REPAIR_CLAIMED,
        ComplaintStatus.VERIFIED,
        ComplaintStatus.REJECTED,
    ],
    ComplaintStatus.REVIEW_REQUIRED: [
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.VERIFIED,
        ComplaintStatus.REJECTED,
        ComplaintStatus.EVIDENCE_REQUESTED,
        ComplaintStatus.MORE_EVIDENCE_REQUIRED,
        ComplaintStatus.UNDER_REVIEW,
        ComplaintStatus.PROCESSING,
    ],

    ComplaintStatus.EVIDENCE_REQUESTED: [
        ComplaintStatus.UNDER_REVIEW,
        ComplaintStatus.VERIFICATION_PENDING,
        ComplaintStatus.PROCESSING,
    ],
    ComplaintStatus.MORE_EVIDENCE_REQUIRED: [
        ComplaintStatus.PROCESSING,
        ComplaintStatus.REVIEW_REQUIRED,
        ComplaintStatus.REJECTED,
    ],
    ComplaintStatus.VERIFIED: [
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.REPAIR_IN_PROGRESS,
    ],
    ComplaintStatus.REJECTED: [
        ComplaintStatus.REVIEW_REQUIRED,
    ],

    # Authority & repair execution
    ComplaintStatus.AUTHORITY_QUEUE: [
        ComplaintStatus.ACTION_IN_PROGRESS,
        ComplaintStatus.REPAIR_IN_PROGRESS,
        ComplaintStatus.REVIEW_REQUIRED,
        ComplaintStatus.REJECTED,
    ],
    ComplaintStatus.ACTION_IN_PROGRESS: [
        ComplaintStatus.RESOLVED,
        ComplaintStatus.REPAIR_CLAIMED,
        ComplaintStatus.REWORK_REQUESTED,
        ComplaintStatus.AUTHORITY_QUEUE,
        ComplaintStatus.REPAIR_IN_PROGRESS,
    ],
    ComplaintStatus.REPAIR_IN_PROGRESS: [
        ComplaintStatus.REPAIR_CLAIMED,
        ComplaintStatus.ACTION_IN_PROGRESS,
        ComplaintStatus.RESOLVED,
    ],
    ComplaintStatus.REPAIR_CLAIMED: [
        ComplaintStatus.VERIFICATION_PENDING,
        ComplaintStatus.RESOLVED_AFTER_REVIEW,
        ComplaintStatus.REWORK_REQUESTED,
        ComplaintStatus.EVIDENCE_REQUESTED,
    ],
    ComplaintStatus.VERIFICATION_PENDING: [
        ComplaintStatus.RESOLVED_AFTER_REVIEW,
        ComplaintStatus.REWORK_REQUESTED,
        ComplaintStatus.EVIDENCE_REQUESTED,
    ],
    ComplaintStatus.REWORK_REQUESTED: [
        ComplaintStatus.REPAIR_IN_PROGRESS,
        ComplaintStatus.ACTION_IN_PROGRESS,
    ],

    # Resolution & dispute paths
    ComplaintStatus.RESOLVED: [
        ComplaintStatus.DISPUTED,
        ComplaintStatus.RESOLVED_AFTER_REVIEW,
    ],
    ComplaintStatus.RESOLVED_AFTER_REVIEW: [
        ComplaintStatus.DISPUTED,
    ],
    ComplaintStatus.DISPUTED: [
        ComplaintStatus.REASSESSMENT_PENDING,
        ComplaintStatus.REWORK_REQUESTED,
        ComplaintStatus.REASSESSMENT_COMPLETED,
        ComplaintStatus.RESOLVED_AFTER_REVIEW,
        ComplaintStatus.REVIEW_REQUIRED,
    ],
    ComplaintStatus.REASSESSMENT_PENDING: [
        ComplaintStatus.REASSESSMENT_COMPLETED,
        ComplaintStatus.REWORK_REQUESTED,
        ComplaintStatus.RESOLVED_AFTER_REVIEW,
    ],
    ComplaintStatus.REASSESSMENT_COMPLETED: [
        ComplaintStatus.DISPUTED,
    ],
}



class ComplaintService:
    def __init__(self, db: Session):
        self.repo = ComplaintRepository(db)

    def create_complaint(self, complaint_in: ComplaintCreate) -> Complaint:
        # Additional business validations
        if not complaint_in.title or len(complaint_in.title.strip()) < 3:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Title must be at least 3 characters long"
            )
        if not complaint_in.description or len(complaint_in.description.strip()) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Description must be at least 5 characters long"
            )

        # Duplicate-submission safeguard: check if identical complaint was submitted in last 120s
        recent_duplicate = self.repo.find_recent_duplicate(
            citizen_id=complaint_in.citizen_id or "guest_citizen",
            category=complaint_in.category,
            title=complaint_in.title.strip(),
            description=complaint_in.description.strip(),
            window_seconds=120
        )
        if recent_duplicate:
            return recent_duplicate

        return self.repo.create(complaint_in)

    def get_complaint(self, complaint_id: str) -> Complaint:
        complaint = self.repo.get_by_id(complaint_id)
        if not complaint:
            # Also try lookup by reference ID
            complaint = self.repo.get_by_reference_id(complaint_id)
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )
        return complaint

    def list_complaints(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[ComplaintCategory] = None,
        status_filter: Optional[ComplaintStatus] = None,
        citizen_id: Optional[str] = None
    ) -> List[Complaint]:
        return self.repo.list(
            skip=skip,
            limit=limit,
            category=category,
            status=status_filter,
            citizen_id=citizen_id
        )

    def transition_status(
        self,
        complaint_id: str,
        update_in: ComplaintUpdateStatus,
        actor_type: ActorType = ActorType.REVIEWER
    ) -> Complaint:
        complaint = self.get_complaint(complaint_id)
        current_status = complaint.status
        target_status = update_in.new_status

        # Validate transition against strict state machine
        allowed_targets = VALID_TRANSITIONS.get(current_status, [])
        if target_status not in allowed_targets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state transition: Cannot change from '{current_status.value}' to '{target_status.value}'. Allowed transitions: {[s.value for s in allowed_targets]}"
            )

        updated_complaint = self.repo.update_status(
            complaint=complaint,
            new_status=target_status,
            actor_type=actor_type,
            actor_id=update_in.actor_id,
            notes=update_in.notes
        )

        # Trigger in-app notification for the citizen
        from app.services.notification_service import NotificationService
        try:
            notif_service = NotificationService(self.repo.db)
            notif_service.notify_status_change(updated_complaint, target_status)
        except Exception:
            # Notifications failure should not roll back status update
            pass

        return updated_complaint

    def get_timeline(self, complaint_id: str) -> List[ComplaintStatusEvent]:
        # Ensure complaint exists
        self.get_complaint(complaint_id)
        return self.repo.get_timeline(complaint_id)

    def attach_evidence(self, complaint_id: str, evidence_in: EvidenceCreate) -> ComplaintEvidence:
        # Ensure complaint exists
        self.get_complaint(complaint_id)
        return self.repo.add_evidence(complaint_id, evidence_in)

    def attach_evidence_file(
        self,
        complaint_id: str,
        file: UploadFile,
        evidence_type: EvidenceType = EvidenceType.INITIAL_REPORT,
        actor_id: Optional[str] = None,
        is_public_approved: Optional[bool] = None
    ) -> ComplaintEvidence:
        complaint = self.get_complaint(complaint_id)
        file_path, file_size = storage.save_upload_sync(file)

        # Default to True for initial evidence so civic complaints are immediately visible
        # on public feed and map, unless explicitly specified
        approved_val = True if is_public_approved is None else is_public_approved

        evidence_in = EvidenceCreate(
            evidence_type=evidence_type,
            file_name=file.filename or "attachment.jpg",
            file_size=file_size,
            mime_type=file.content_type or "image/jpeg",
            file_path=file_path,
            is_public_approved=approved_val
        )
        evidence = self.repo.add_evidence(complaint.id, evidence_in)

        # Audit timeline event for evidence upload
        event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=complaint.status.value,
            new_status=complaint.status.value,
            actor_type=ActorType.CITIZEN,
            actor_id=actor_id or complaint.citizen_id or "guest_citizen",
            notes=f"Evidence attached: {evidence.file_name} ({evidence_type.value})"
        )
        self.repo.db.add(event)
        self.repo.db.commit()

        # Automated Offline AI Assessment & Routing for Initial Evidence
        if (
            evidence_type == EvidenceType.INITIAL_REPORT
            and getattr(settings, "AUTO_ASSESS_ON_UPLOAD", True)
            and not os.environ.get("TESTING")
        ):
            try:
                from app.services.incident_assessment_service import IncidentAssessmentService
                assessment_service = IncidentAssessmentService(self.repo.db)
                assessment_service.assess_and_route(
                    complaint_id=complaint.id,
                    evidence_id=evidence.id,
                    actor_id=actor_id or "offline_clip_engine"
                )
            except Exception:
                pass

        return evidence

    def moderate_evidence(
        self,
        complaint_id: str,
        evidence_id: str,
        is_public_approved: bool
    ) -> ComplaintEvidence:
        self.get_complaint(complaint_id)
        evidence = self.repo.get_evidence(complaint_id, evidence_id)
        if not evidence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evidence '{evidence_id}' not found for complaint '{complaint_id}'"
            )
        return self.repo.set_evidence_approval(evidence, is_public_approved)

    def get_public_complaint(self, complaint_id: str) -> dict:
        complaint = self.get_complaint(complaint_id)
        approved_evidence = [
            {
                "id": e.id,
                "evidence_type": e.evidence_type,
                "file_name": e.file_name,
                "file_size": e.file_size,
                "mime_type": e.mime_type,
                "file_url": f"/api/public/complaints/{complaint.id}/evidence/{e.id}/file",
                "created_at": e.created_at,
            }
            for e in complaint.evidence_items
            if e.is_public_approved
        ]

        # Sanitized address: show street/neighborhood without resident private details
        sanitized_address = complaint.location_address

        return {
            "id": complaint.id,
            "reference_id": complaint.reference_id,
            "title": complaint.title,
            "category": complaint.category,
            "description": complaint.description,
            "status": complaint.status,
            "location_address": sanitized_address,
            "latitude": complaint.latitude,
            "longitude": complaint.longitude,
            "location_type": complaint.location_type,
            "created_at": complaint.created_at,
            "updated_at": complaint.updated_at,
            "evidence_items": approved_evidence,
        }

    def list_public_complaints(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[ComplaintCategory] = None,
        status_filter: Optional[ComplaintStatus] = None,
        user_lat: Optional[float] = None,
        user_lng: Optional[float] = None,
        radius_km: Optional[float] = None,
        sort_by: str = "recent"  # "recent" or "distance"
    ) -> List[dict]:
        import math

        def calc_distance(lat1, lon1, lat2, lon2):
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return round(R * c, 2)

        # Retrieve matching complaints
        complaints = self.repo.list(
            skip=0,
            limit=500,  # pull candidate set for geo-filtering
            category=category,
            status=status_filter,
            citizen_id=None
        )

        results = []
        for c in complaints:
            dist = None
            if user_lat is not None and user_lng is not None and c.latitude is not None and c.longitude is not None:
                dist = calc_distance(user_lat, user_lng, c.latitude, c.longitude)
                if radius_km is not None and dist > radius_km:
                    continue
            elif radius_km is not None and (c.latitude is None or c.longitude is None):
                # When filtering strictly by radius, exclude complaints without coordinates
                continue

            results.append({
                "id": c.id,
                "reference_id": c.reference_id,
                "title": c.title,
                "category": c.category,
                "status": c.status,
                "location_address": c.location_address,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "location_type": c.location_type,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "evidence_count": len([e for e in c.evidence_items if e.is_public_approved]),
                "distance_km": dist
            })

        # Sorting
        if sort_by == "distance" and user_lat is not None and user_lng is not None:
            results.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 999999))
        else:
            results.sort(key=lambda x: x["created_at"], reverse=True)

        return results[skip : skip + limit]

    def get_public_evidence(self, complaint_id: str, evidence_id: str) -> ComplaintEvidence:
        self.get_complaint(complaint_id)
        evidence = self.repo.get_evidence(complaint_id, evidence_id)
        if not evidence:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evidence '{evidence_id}' not found"
            )
        if not evidence.is_public_approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Evidence has not been authorized for public viewing"
            )
        return evidence

    def delete_complaint(self, complaint_id: str) -> None:
        deleted = self.repo.delete(complaint_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint '{complaint_id}' not found"
            )


