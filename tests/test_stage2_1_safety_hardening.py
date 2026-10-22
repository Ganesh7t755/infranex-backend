import math
import os
import pytest
from fastapi import status
from PIL import Image

from app.core.config import settings
from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.incident_assessment import IncidentAssessment
from app.services.incident_assessment_provider import (
    DeterministicMockAssessmentProvider,
    IncidentAssessmentInput,
    IncidentAssessmentResult,
)
from app.services.incident_assessment_service import (
    IncidentAssessmentService,
    ELIGIBLE_ASSESSMENT_STATES,
)


def create_test_image(path: str, width: int = 300, height: int = 300, color: str = "gray"):
    """Creates a valid test image file on disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")


@pytest.fixture
def owner_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-TEST-OWNER-001",
        title="Owner pothole issue",
        category=ComplaintCategory.POTHOLE,
        description="Hazardous street pothole",
        status=ComplaintStatus.SUBMITTED,
        location_type=LocationType.GPS,
        citizen_id="citizen_alice"
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.refresh(complaint)
    return complaint


@pytest.fixture
def second_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-TEST-BOB-002",
        title="Bob's garbage complaint",
        category=ComplaintCategory.GARBAGE,
        description="Piled up trash",
        status=ComplaintStatus.SUBMITTED,
        location_type=LocationType.GPS,
        citizen_id="citizen_bob"
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.refresh(complaint)
    return complaint


@pytest.fixture
def owner_evidence(db_session, owner_complaint, tmp_path):
    img_path = str(tmp_path / "alice_pothole.jpg")
    create_test_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=owner_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="alice_pothole.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg",
        is_public_approved=False
    )
    db_session.add(evidence)
    db_session.commit()
    db_session.refresh(evidence)
    return evidence


# ============================================================================
# 1. Anonymous assessment creation is denied (401)
# ============================================================================

def test_anonymous_assessment_creation_denied(client, owner_complaint, owner_evidence):
    # Completely anonymous call without any auth headers -> 401 Unauthorized
    res = client.post(
        f"/api/complaints/{owner_complaint.id}/assessments?evidence_id={owner_evidence.id}"
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Authentication required" in res.json().get("detail", "")

    # Blank/empty user ID header -> 401 Unauthorized
    res_blank = client.post(
        f"/api/complaints/{owner_complaint.id}/assessments?evidence_id={owner_evidence.id}",
        headers={"X-User-ID": "   "}
    )
    assert res_blank.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# 2. A citizen cannot trigger an assessment for another citizen's complaint (403)
# ============================================================================

def test_citizen_cannot_trigger_assessment_for_another_citizen(client, owner_complaint, owner_evidence):
    # Attacker citizen Bob attempts to trigger assessment on Alice's complaint -> 403 Forbidden
    res = client.post(
        f"/api/complaints/{owner_complaint.id}/assessments?evidence_id={owner_evidence.id}",
        headers={"X-User-ID": "citizen_bob"}
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "Access denied" in res.json().get("detail", "")


# ============================================================================
# 3. A citizen cannot read another citizen's assessment history (403)
# ============================================================================

def test_citizen_cannot_read_another_citizens_assessment_history(client, owner_complaint, owner_evidence, db_session):
    # First, legitimately create an assessment by the owner
    service = IncidentAssessmentService(db_session)
    service.assess_and_route(owner_complaint.id, owner_evidence.id, actor_id="citizen_alice")

    # Anonymous reading history -> 401 Unauthorized
    res_anon = client.get(f"/api/complaints/{owner_complaint.id}/assessments")
    assert res_anon.status_code == status.HTTP_401_UNAUTHORIZED

    # Unrelated citizen Bob reading Alice's history -> 403 Forbidden
    res_bob = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-User-ID": "citizen_bob"}
    )
    assert res_bob.status_code == status.HTTP_403_FORBIDDEN

    # Owner Alice reading her own history -> 200 OK
    res_alice = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-User-ID": "citizen_alice"}
    )
    assert res_alice.status_code == status.HTTP_200_OK
    assert len(res_alice.json()) >= 1


# ============================================================================
# 4. Assessment-by-ID retrieval applies the same access rules (401/403/404)
# ============================================================================

def test_assessment_by_id_retrieval_applies_access_rules(client, owner_complaint, owner_evidence, second_complaint, db_session):
    service = IncidentAssessmentService(db_session)
    assessment, _ = service.assess_and_route(owner_complaint.id, owner_evidence.id, actor_id="citizen_alice")
    aid = assessment.id

    # Anonymous -> 401
    res_anon = client.get(f"/api/complaints/{owner_complaint.id}/assessments/{aid}")
    assert res_anon.status_code == status.HTTP_401_UNAUTHORIZED

    # Unauthorized citizen Bob -> 403
    res_bob = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments/{aid}",
        headers={"X-User-ID": "citizen_bob"}
    )
    assert res_bob.status_code == status.HTTP_403_FORBIDDEN

    # Legitimate owner Alice -> 200
    res_alice = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments/{aid}",
        headers={"X-User-ID": "citizen_alice"}
    )
    assert res_alice.status_code == status.HTTP_200_OK
    assert res_alice.json()["id"] == aid

    # Bob tries to access Alice's assessment through Bob's complaint URL -> 404 Not Found
    res_cross = client.get(
        f"/api/complaints/{second_complaint.id}/assessments/{aid}",
        headers={"X-User-ID": "citizen_bob"}
    )
    assert res_cross.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 5. Reviewer access is allowed only when authentication genuinely establishes role
# ============================================================================

def test_reviewer_access_genuine_establishment(client, owner_complaint, owner_evidence, db_session):
    # 5a. Legitimate reviewer via X-Role: REVIEWER can trigger and read
    res_rev = client.post(
        f"/api/complaints/{owner_complaint.id}/assessments?evidence_id={owner_evidence.id}",
        headers={"X-Role": "REVIEWER", "X-Reviewer-ID": "staff_reviewer_01"}
    )
    assert res_rev.status_code == status.HTTP_201_CREATED
    aid = res_rev.json()["id"]

    res_list = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-Role": "REVIEWER"}
    )
    assert res_list.status_code == status.HTTP_200_OK

    res_get = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments/{aid}",
        headers={"X-Role": "REVIEWER"}
    )
    assert res_get.status_code == status.HTTP_200_OK

    # 5b. Legitimate reviewer via valid token
    dev_token = getattr(settings, "DEV_REVIEWER_TOKEN", "infranex-dev-reviewer-secret-key-stage5")
    res_token = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-Reviewer-Token": dev_token}
    )
    assert res_token.status_code == status.HTTP_200_OK

    # 5c. Fake role (e.g. X-Role: ADMIN or X-Role: REVIEW_OFFICER) for another citizen's complaint -> 403
    res_fake_role = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-User-ID": "citizen_bob", "X-Role": "ADMIN"}
    )
    assert res_fake_role.status_code == status.HTTP_403_FORBIDDEN

    # 5d. Invalid token -> 403
    res_bad_token = client.get(
        f"/api/complaints/{owner_complaint.id}/assessments",
        headers={"X-User-ID": "citizen_bob", "X-Reviewer-Token": "invalid_fake_secret"}
    )
    assert res_bad_token.status_code == status.HTTP_403_FORBIDDEN

    # 5e. Production mode rejects header assertions
    original_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        res_prod = client.get(
            f"/api/complaints/{owner_complaint.id}/assessments",
            headers={"X-Role": "REVIEWER"}
        )
        assert res_prod.status_code == status.HTTP_403_FORBIDDEN
        assert "Header-based authentication is disabled in production" in res_prod.json().get("detail", "")
    finally:
        settings.ENVIRONMENT = original_env


# ============================================================================
# 6. A resolved or other ineligible complaint cannot be reassessed
# ============================================================================

def test_resolved_and_ineligible_complaints_cannot_be_reassessed(db_session, owner_evidence):
    service = IncidentAssessmentService(db_session)

    ineligible_states = [
        ComplaintStatus.RESOLVED,
        ComplaintStatus.REJECTED,
        ComplaintStatus.ACTION_IN_PROGRESS,
        ComplaintStatus.VERIFICATION_PENDING
    ]

    for st in ineligible_states:
        complaint = Complaint(
            reference_id=f"INFRA-INELIGIBLE-{st.value}",
            title="Ineligible complaint",
            category=ComplaintCategory.POTHOLE,
            description="Detailed defect description",
            status=st,
            citizen_id="citizen_alice"
        )
        db_session.add(complaint)
        db_session.commit()

        with pytest.raises(Exception) as exc_info:
            service.assess_and_route(complaint.id, evidence_id=None)

        assert f"Cannot assess complaint in lifecycle state '{st.value}'" in str(exc_info.value)
        # Verify status did not change
        db_session.refresh(complaint)
        assert complaint.status == st


# ============================================================================
# 7. Rejected reassessment does not create misleading record or mutate state
# ============================================================================

def test_rejected_reassessment_does_not_mutate_state_or_persist_record(db_session):
    complaint = Complaint(
        reference_id="INFRA-RESOLVED-IMMUTABLE",
        title="Closed and resolved pothole",
        category=ComplaintCategory.POTHOLE,
        description="Detailed defect description",
        status=ComplaintStatus.RESOLVED,
        citizen_id="citizen_alice"
    )
    db_session.add(complaint)
    db_session.commit()

    count_before = db_session.query(IncidentAssessment).filter(IncidentAssessment.complaint_id == complaint.id).count()

    service = IncidentAssessmentService(db_session)
    with pytest.raises(Exception):
        service.assess_and_route(complaint.id)

    db_session.refresh(complaint)
    count_after = db_session.query(IncidentAssessment).filter(IncidentAssessment.complaint_id == complaint.id).count()

    assert count_after == count_before == 0
    assert complaint.status == ComplaintStatus.RESOLVED


# ============================================================================
# 8. NaN, positive/negative infinity and out-of-range confidence handling
# ============================================================================

def test_nan_infinity_and_out_of_range_confidence_handling(db_session, owner_complaint, owner_evidence):
    # Direct validation check
    assert IncidentAssessmentService._validate_confidence_score(float('nan')) is None
    assert IncidentAssessmentService._validate_confidence_score(float('inf')) is None
    assert IncidentAssessmentService._validate_confidence_score(float('-inf')) is None
    assert IncidentAssessmentService._validate_confidence_score(1.5) is None
    assert IncidentAssessmentService._validate_confidence_score(-0.01) is None
    assert IncidentAssessmentService._validate_confidence_score("unparseable") is None
    assert IncidentAssessmentService._validate_confidence_score(0.0) == 0.0
    assert IncidentAssessmentService._validate_confidence_score(0.95) == 0.95
    assert IncidentAssessmentService._validate_confidence_score(1.0) == 1.0

    # Ensure provider returning NaN never enters AUTHORITY_QUEUE
    class MockNaNProvider(DeterministicMockAssessmentProvider):
        def assess_incident(self, input_data):
            res = super().assess_incident(input_data)
            res.confidence_score = float('nan')
            return res

    service = IncidentAssessmentService(db_session)
    service.provider = MockNaNProvider()

    assessment, updated_complaint = service.assess_and_route(owner_complaint.id, owner_evidence.id)
    assert assessment.confidence_score is None
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED


# ============================================================================
# 9. Missing-file and provider exceptions do not leak absolute paths or raw traces
# ============================================================================

def test_missing_file_and_provider_exceptions_do_not_leak_paths(db_session, owner_complaint):
    # 9a. Missing file path on disk
    secret_path = os.path.abspath("E:/super_confidential_directory/secret_photo.jpg")
    missing_evidence = ComplaintEvidence(
        complaint_id=owner_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=secret_path,
        file_name="secret_photo.jpg",
        file_size=1024,
        mime_type="image/jpeg"
    )
    db_session.add(missing_evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_c = service.assess_and_route(owner_complaint.id, missing_evidence.id)

    # Must NOT leak secret_path
    metadata_str = str(assessment.assessment_metadata)
    explanation_str = str(assessment.explanation)
    assert "super_confidential_directory" not in metadata_str
    assert "super_confidential_directory" not in explanation_str
    assert assessment.assessment_metadata.get("error_code") == "FILE_NOT_FOUND"
    assert assessment.assessment_metadata.get("evidence_name") == "secret_photo.jpg"
    assert assessment.is_simulation is True

    # 9b. Provider raising raw exception with internal server details
    class LeakyMockProvider(DeterministicMockAssessmentProvider):
        def assess_incident(self, input_data):
            raise RuntimeError("Database password leaked in C:\\internal\\secret.env at line 42")

    service.provider = LeakyMockProvider()
    # Complaint is in REVIEW_REQUIRED now, which is eligible for re-assessment
    assessment2, updated_c2 = service.assess_and_route(owner_complaint.id, missing_evidence.id)

    metadata_str2 = str(assessment2.assessment_metadata)
    explanation_str2 = str(assessment2.explanation)
    assert "secret.env" not in metadata_str2
    assert "password" not in metadata_str2
    assert "secret.env" not in explanation_str2
    assert assessment2.assessment_metadata.get("error_code") == "PROVIDER_PROCESSING_ERROR"
    assert assessment2.assessment_metadata.get("exception_type") == "RuntimeError"
    assert assessment2.is_simulation is True
    assert updated_c2.status == ComplaintStatus.REVIEW_REQUIRED
