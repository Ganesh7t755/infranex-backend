import os
import pytest
from PIL import Image

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.assignment import ComplaintAssignment
from app.models.review_decision import ReviewDecisionAction
from app.services.incident_assessment_service import IncidentAssessmentService
from app.services.reviewer_service import ReviewerService, ReviewDecisionCreate
from app.core.security import create_access_token

def create_test_image(path: str, width: int = 200, height: int = 200, color: str = "red"):
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")

@pytest.fixture
def sample_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-STAGE7-001",
        title="Hazardous asphalt pothole on 4th Ave",
        category=ComplaintCategory.POTHOLE,
        description="Deep crater damaging passing vehicle tires",
        status=ComplaintStatus.SUBMITTED,
        location_type=LocationType.GPS,
        citizen_id="citizen_tester"
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.refresh(complaint)
    return complaint

class TestStage7RoutingBoundaries:
    """Tests for exact 90% AI confidence threshold rule and overrides."""

    def test_threshold_8999_routes_to_human_review(self, db_session, sample_complaint, tmp_path):
        """0.8999 <= 0.9000 must route to Human Review (REVIEW_REQUIRED)."""
        img_path = str(tmp_path / "score_8999.jpg")
        create_test_image(img_path)
        evidence = ComplaintEvidence(
            complaint_id=sample_complaint.id,
            evidence_type=EvidenceType.INITIAL_REPORT,
            file_path=img_path,
            file_name="score_8999.jpg",
            file_size=os.path.getsize(img_path),
            mime_type="image/jpeg"
        )
        db_session.add(evidence)
        db_session.commit()

        service = IncidentAssessmentService(db_session)
        assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

        assert assessment.confidence_score == 0.8999
        assert assessment.review_required is True
        assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

    def test_threshold_9000_routes_to_human_review(self, db_session, sample_complaint, tmp_path):
        """Exact 0.9000 <= 0.9000 must route to Human Review (REVIEW_REQUIRED)."""
        img_path = str(tmp_path / "score_9000.jpg")
        create_test_image(img_path)
        evidence = ComplaintEvidence(
            complaint_id=sample_complaint.id,
            evidence_type=EvidenceType.INITIAL_REPORT,
            file_path=img_path,
            file_name="score_9000.jpg",
            file_size=os.path.getsize(img_path),
            mime_type="image/jpeg"
        )
        db_session.add(evidence)
        db_session.commit()

        service = IncidentAssessmentService(db_session)
        assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

        assert assessment.confidence_score == 0.9000
        assert assessment.review_required is True
        assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

    def test_threshold_9001_routes_to_authority_queue(self, db_session, sample_complaint, tmp_path):
        """0.9001 > 0.9000 routes directly to Authority Queue when gates pass."""
        img_path = str(tmp_path / "score_9001.jpg")
        create_test_image(img_path)
        evidence = ComplaintEvidence(
            complaint_id=sample_complaint.id,
            evidence_type=EvidenceType.INITIAL_REPORT,
            file_path=img_path,
            file_name="score_9001.jpg",
            file_size=os.path.getsize(img_path),
            mime_type="image/jpeg"
        )
        db_session.add(evidence)
        db_session.commit()

        service = IncidentAssessmentService(db_session)
        assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

        assert assessment.confidence_score == 0.9001
        assert assessment.review_required is False
        assert updated_complaint.status == ComplaintStatus.AUTHORITY_QUEUE
        assert updated_complaint.service_domain is not None
        assert updated_complaint.assigned_department is not None

        # Verify persistent assignment audit
        assignment = db_session.query(ComplaintAssignment).filter(
            ComplaintAssignment.complaint_id == sample_complaint.id
        ).first()
        assert assignment is not None
        assert assignment.assigned_by == "ai_confidence_routing_engine"

    def test_high_confidence_mismatch_overrides_to_human_review(self, db_session, sample_complaint, tmp_path):
        """Even with high score (0.95), category mismatch overrides to REVIEW_REQUIRED."""
        img_path = str(tmp_path / "mismatch_evidence.jpg")
        create_test_image(img_path)
        evidence = ComplaintEvidence(
            complaint_id=sample_complaint.id,
            evidence_type=EvidenceType.INITIAL_REPORT,
            file_path=img_path,
            file_name="mismatch_evidence.jpg",
            file_size=os.path.getsize(img_path),
            mime_type="image/jpeg"
        )
        db_session.add(evidence)
        db_session.commit()

        service = IncidentAssessmentService(db_session)
        assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

        assert assessment.confidence_score == 0.95
        assert assessment.category_match is False
        assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED


class TestStage7AuthenticationAndRoles:
    """Tests for secure JWT-based auth and role boundary enforcement."""

    def test_staff_login_authority_success(self, client):
        response = client.post(
            "/api/auth/login",
            json={"staff_id": "auth-001", "password": "AuthorityPassword2026!", "role": "AUTHORITY"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "AUTHORITY"
        assert data["user_id"] == "auth-001"

    def test_staff_login_reviewer_success(self, client):
        response = client.post(
            "/api/auth/login",
            json={"staff_id": "rev-001", "password": "ReviewerPassword2026!", "role": "REVIEWER"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "REVIEWER"
        assert data["user_id"] == "rev-001"

    def test_staff_login_invalid_credentials_rejected(self, client):
        response = client.post(
            "/api/auth/login",
            json={"staff_id": "auth-001", "password": "WrongPassword", "role": "AUTHORITY"}
        )
        assert response.status_code == 401

    def test_cross_role_access_denial(self, client):
        """Reviewer JWT must NOT be allowed to call Authority Queue."""
        rev_token = create_access_token(user_id="rev-001", role="REVIEWER")
        headers = {"Authorization": f"Bearer {rev_token}"}

        resp = client.get("/api/authority/queue", headers=headers)
        assert resp.status_code == 403

    def test_authority_jwt_can_access_authority_queue(self, client):
        auth_token = create_access_token(user_id="auth-001", role="AUTHORITY", department="Public Works")
        headers = {"Authorization": f"Bearer {auth_token}"}

        resp = client.get("/api/authority/queue", headers=headers)
        assert resp.status_code == 200


from app.core.security import create_access_token, ReviewerIdentity

class TestStage7ReviewerDecisionsAndAssignments:
    """Tests for Human Reviewer approve, request evidence, and reject outcomes."""

    def test_reviewer_approve_routes_to_authorities(self, db_session, sample_complaint):
        sample_complaint.status = ComplaintStatus.REVIEW_REQUIRED
        sample_complaint.category = ComplaintCategory.POTHOLE
        db_session.commit()

        service = ReviewerService(db_session)
        decision_in = ReviewDecisionCreate(
            action=ReviewDecisionAction.APPROVE,
            reason="Pothole verified via manual street-view inspection.",
            notes="Routing to Roads department for repair"
        )
        record = service.submit_review_decision(
            complaint_id=sample_complaint.id,
            decision_in=decision_in,
            reviewer=ReviewerIdentity(reviewer_id="rev-001")
        )

        assert record.action == ReviewDecisionAction.APPROVE
        db_session.refresh(sample_complaint)
        assert sample_complaint.status == ComplaintStatus.AUTHORITY_QUEUE
        assert sample_complaint.service_domain == "ROADS"
        assert sample_complaint.assigned_department == "BBMP - Road Infrastructure Division"

    def test_reviewer_request_evidence(self, db_session, sample_complaint):
        sample_complaint.status = ComplaintStatus.REVIEW_REQUIRED
        db_session.commit()

        service = ReviewerService(db_session)
        decision_in = ReviewDecisionCreate(
            action=ReviewDecisionAction.REQUEST_EVIDENCE,
            reason="Please capture an image showing the full extent of the water leak.",
            notes="Need wider camera angle"
        )
        record = service.submit_review_decision(
            complaint_id=sample_complaint.id,
            decision_in=decision_in,
            reviewer=ReviewerIdentity(reviewer_id="rev-001")
        )

        assert record.action == ReviewDecisionAction.REQUEST_EVIDENCE
        db_session.refresh(sample_complaint)
        assert sample_complaint.status == ComplaintStatus.EVIDENCE_REQUESTED

    def test_reviewer_reject_requires_reason(self, db_session, sample_complaint):
        sample_complaint.status = ComplaintStatus.REVIEW_REQUIRED
        db_session.commit()

        service = ReviewerService(db_session)
        # Attempt reject with short/empty reason
        with pytest.raises(Exception):
            decision_in = ReviewDecisionCreate(
                action=ReviewDecisionAction.REJECT,
                reason="no"
            )
            service.submit_review_decision(
                complaint_id=sample_complaint.id,
                decision_in=decision_in,
                reviewer=ReviewerIdentity(reviewer_id="rev-001")
            )

        # Valid reject
        valid_decision = ReviewDecisionCreate(
            action=ReviewDecisionAction.REJECT,
            reason="Duplicate of incident INF-2026-0012, already under repair."
        )
        record = service.submit_review_decision(
            complaint_id=sample_complaint.id,
            decision_in=valid_decision,
            reviewer=ReviewerIdentity(reviewer_id="rev-001")
        )
        assert record.action == ReviewDecisionAction.REJECT
        db_session.refresh(sample_complaint)
        assert sample_complaint.status == ComplaintStatus.REJECTED


class TestStage7MultiDomainAuthorityQueue:
    """Tests for multi-domain dashboard and domain filtering."""

    def test_multi_domain_queue_and_filtering(self, db_session, client):
        # Create electricity complaint
        c1 = Complaint(
            reference_id="INF-ELEC-701",
            title="Transformer sparking near substation",
            description="BESCOM transformer sparking violently",
            category=ComplaintCategory.OTHER,
            status=ComplaintStatus.AUTHORITY_QUEUE,
            service_domain="ELECTRICITY",
            assigned_department="Electricity Board (BESCOM)",
            assignment_status="ASSIGNED",
            citizen_id="cit-001"
        )
        # Create sanitation complaint
        c2 = Complaint(
            reference_id="INF-SAN-702",
            title="Garbage overflow on Main Road",
            description="Piled up solid waste obstructing footpath",
            category=ComplaintCategory.GARBAGE,
            status=ComplaintStatus.AUTHORITY_QUEUE,
            service_domain="SANITATION",
            assigned_department="Solid Waste Management",
            assignment_status="ASSIGNED",
            citizen_id="cit-002"
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        auth_token = create_access_token(user_id="auth-super", role="AUTHORITY")
        headers = {"Authorization": f"Bearer {auth_token}"}

        # 1. Fetch all domains
        resp_all = client.get("/api/authority/queue", headers=headers)
        assert resp_all.status_code == 200
        items = resp_all.json()
        ids = [item["id"] for item in items]
        assert c1.id in ids
        assert c2.id in ids

        # 2. Filter by ELECTRICITY
        resp_elec = client.get("/api/authority/queue?domain=ELECTRICITY", headers=headers)
        assert resp_elec.status_code == 200
        elec_items = resp_elec.json()
        elec_ids = [item["id"] for item in elec_items]
        assert c1.id in elec_ids
        assert c2.id not in elec_ids

        # 3. Filter by SANITATION
        resp_san = client.get("/api/authority/queue?domain=SANITATION", headers=headers)
        assert resp_san.status_code == 200
        san_items = resp_san.json()
        san_ids = [item["id"] for item in san_items]
        assert c2.id in san_ids
        assert c1.id not in san_ids
