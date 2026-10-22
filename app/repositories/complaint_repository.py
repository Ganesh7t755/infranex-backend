import random
import string
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.schemas.complaint import ComplaintCreate
from app.schemas.evidence import EvidenceCreate

class ComplaintRepository:
    def __init__(self, db: Session):
        self.db = db

    def _generate_reference_id(self) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        rand_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"INF-{date_str}-{rand_str}"

    def find_recent_duplicate(
        self,
        citizen_id: str,
        category: ComplaintCategory,
        title: str,
        description: str,
        window_seconds: int = 120
    ) -> Optional[Complaint]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        return (
            self.db.query(Complaint)
            .filter(
                Complaint.citizen_id == citizen_id,
                Complaint.category == category,
                Complaint.title == title,
                Complaint.description == description,
                Complaint.created_at >= cutoff
            )
            .order_by(desc(Complaint.created_at))
            .first()
        )

    def create(self, complaint_in: ComplaintCreate) -> Complaint:
        ref_id = self._generate_reference_id()
        
        # Verify reference uniqueness
        while self.get_by_reference_id(ref_id) is not None:
            ref_id = self._generate_reference_id()

        db_complaint = Complaint(
            reference_id=ref_id,
            title=complaint_in.title,
            category=complaint_in.category,
            description=complaint_in.description,
            status=ComplaintStatus.SUBMITTED,
            location_address=complaint_in.location_address,
            latitude=complaint_in.latitude,
            longitude=complaint_in.longitude,
            location_type=complaint_in.location_type,
            citizen_id=complaint_in.citizen_id or "guest_citizen",
        )
        self.db.add(db_complaint)
        self.db.flush()

        # Record initial status event in timeline
        initial_event = ComplaintStatusEvent(
            complaint_id=db_complaint.id,
            previous_status=None,
            new_status=ComplaintStatus.SUBMITTED.value,
            actor_type=ActorType.CITIZEN,
            actor_id=complaint_in.citizen_id or "guest_citizen",
            notes="Issue submitted by citizen"
        )
        self.db.add(initial_event)
        self.db.commit()
        self.db.refresh(db_complaint)
        return db_complaint

    def get_by_id(self, complaint_id: str) -> Optional[Complaint]:
        return self.db.query(Complaint).filter(Complaint.id == complaint_id).first()

    def get_by_reference_id(self, ref_id: str) -> Optional[Complaint]:
        return self.db.query(Complaint).filter(Complaint.reference_id == ref_id).first()

    def list(
        self,
        skip: int = 0,
        limit: int = 50,
        category: Optional[ComplaintCategory] = None,
        status: Optional[ComplaintStatus] = None,
        citizen_id: Optional[str] = None
    ) -> List[Complaint]:
        query = self.db.query(Complaint)
        if category:
            query = query.filter(Complaint.category == category)
        if status:
            query = query.filter(Complaint.status == status)
        if citizen_id:
            query = query.filter(Complaint.citizen_id == citizen_id)
        return query.order_by(desc(Complaint.created_at)).offset(skip).limit(limit).all()

    def update_status(
        self,
        complaint: Complaint,
        new_status: ComplaintStatus,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Complaint:
        previous_status = complaint.status.value
        complaint.status = new_status
        complaint.updated_at = datetime.now(timezone.utc)

        status_event = ComplaintStatusEvent(
            complaint_id=complaint.id,
            previous_status=previous_status,
            new_status=new_status.value,
            actor_type=actor_type,
            actor_id=actor_id,
            notes=notes
        )
        self.db.add(status_event)
        self.db.commit()
        self.db.refresh(complaint)
        return complaint

    def get_timeline(self, complaint_id: str) -> List[ComplaintStatusEvent]:
        return (
            self.db.query(ComplaintStatusEvent)
            .filter(ComplaintStatusEvent.complaint_id == complaint_id)
            .order_by(ComplaintStatusEvent.created_at.asc())
            .all()
        )

    def add_evidence(
        self,
        complaint_id: str,
        evidence_in: EvidenceCreate
    ) -> ComplaintEvidence:
        evidence = ComplaintEvidence(
            complaint_id=complaint_id,
            evidence_type=evidence_in.evidence_type,
            file_path=evidence_in.file_path,
            file_name=evidence_in.file_name,
            file_size=evidence_in.file_size,
            mime_type=evidence_in.mime_type,
            is_public_approved=evidence_in.is_public_approved,
        )
        self.db.add(evidence)
        self.db.commit()
        self.db.refresh(evidence)
        return evidence

    def get_evidence(self, complaint_id: str, evidence_id: str) -> Optional[ComplaintEvidence]:
        return (
            self.db.query(ComplaintEvidence)
            .filter(ComplaintEvidence.complaint_id == complaint_id, ComplaintEvidence.id == evidence_id)
            .first()
        )

    def set_evidence_approval(self, evidence: ComplaintEvidence, is_approved: bool) -> ComplaintEvidence:
        evidence.is_public_approved = is_approved
        self.db.commit()
        self.db.refresh(evidence)
        return evidence

    def delete(self, complaint_id: str) -> bool:
        complaint = self.get_by_id(complaint_id)
        if not complaint:
            complaint = self.get_by_reference_id(complaint_id)
        if not complaint:
            return False
        self.db.delete(complaint)
        self.db.commit()
        return True

