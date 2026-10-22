import os
import io
import pytest
from PIL import Image

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
    HIGH_CONFIDENCE_THRESHOLD,
)

def create_valid_image(path: str, width: int = 300, height: int = 300, color: str = "gray"):
    """Helper to generate a real, readable JPEG on disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")

def create_corrupt_file(path: str):
    """Helper to generate an invalid/corrupt binary file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00\x01\x02\x03\xffINVALID_HEADER_DATA_12345")

@pytest.fixture
def sample_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-STAGE2-001",
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

@pytest.fixture
def sample_evidence(db_session, sample_complaint, tmp_path):
    img_path = str(tmp_path / "evidence_pothole.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="evidence_pothole.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg",
        is_public_approved=False
    )
    db_session.add(evidence)
    db_session.commit()
    db_session.refresh(evidence)
    return evidence

# ============================================================================
# 1. Provider Interface Contract & Deterministic Mock Output
# ============================================================================

def test_provider_contract_and_deterministic_mock(sample_complaint, sample_evidence):
    provider = DeterministicMockAssessmentProvider()
    inp = IncidentAssessmentInput(
        complaint_id=sample_complaint.id,
        category="POTHOLE",
        title=sample_complaint.title,
        description=sample_complaint.description,
        evidence_id=sample_evidence.id,
        evidence_path=sample_evidence.file_path,
        evidence_name=sample_evidence.file_name,
        mime_type=sample_evidence.mime_type,
        file_size=sample_evidence.file_size
    )
    result = provider.assess_incident(inp)
    assert isinstance(result, IncidentAssessmentResult)
    assert result.provider_id == "mock_deterministic_assessment_v1"
    assert result.model_name == "infranex-suitability-simulator-v1"
    assert result.is_simulation is True
    assert result.confidence_score is not None
    assert 0.0 <= result.confidence_score <= 1.0
    assert result.detected_category == "POTHOLE"
    assert result.category_match is True
    assert result.evidence_suitable is True
    assert "width" in result.assessment_metadata
    assert "height" in result.assessment_metadata

# ============================================================================
# 2. Boundary Scores: 0.89, 0.90, 0.91
# ============================================================================

def test_boundary_score_89_routes_to_human_review(db_session, sample_complaint, tmp_path):
    # Boundary 0.89 is < 0.90 -> Must route to REVIEW_REQUIRED
    img_path = str(tmp_path / "score_89.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="score_89.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score == 0.89
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_boundary_score_90_routes_to_human_review(db_session, sample_complaint, tmp_path):
    # Boundary 0.9000 is <= 0.90 -> Routes to Human Review per strict policy
    img_path = str(tmp_path / "score_90.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="score_90.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score == 0.90
    assert assessment.category_match is True
    assert assessment.evidence_suitable is True
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_boundary_score_9001_routes_to_authority_queue(db_session, sample_complaint, tmp_path):
    # Boundary 0.9001 is > 0.90 -> Eligible for AUTHORITY_QUEUE when all gates pass
    img_path = str(tmp_path / "score_9001.jpg")
    create_valid_image(img_path)
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
    assert assessment.category_match is True
    assert assessment.evidence_suitable is True
    assert assessment.review_required is False
    assert updated_complaint.status == ComplaintStatus.AUTHORITY_QUEUE

def test_boundary_score_91_routes_to_authority_queue(db_session, sample_complaint, tmp_path):
    # Boundary 0.91 is >= 0.90 -> Routes to AUTHORITY_QUEUE
    img_path = str(tmp_path / "score_91.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="score_91.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score == 0.91
    assert assessment.review_required is False
    assert updated_complaint.status == ComplaintStatus.AUTHORITY_QUEUE

# ============================================================================
# 3. High Confidence with Category Mismatch or Unsuitable Evidence
# ============================================================================

def test_high_confidence_with_category_mismatch_must_not_bypass_review(db_session, sample_complaint, tmp_path):
    # High confidence (0.95) but category mismatch -> MUST route to REVIEW_REQUIRED
    img_path = str(tmp_path / "wrong_category_mismatch.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="wrong_category_mismatch.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score == 0.95
    assert assessment.category_match is False
    assert assessment.detected_category != sample_complaint.category.value
    # Crucial safety invariant: Must not bypass human review
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_high_confidence_with_unsuitable_or_blurry_evidence(db_session, sample_complaint, tmp_path):
    # Unsuitable/blurry photo -> MUST route to REVIEW_REQUIRED
    img_path = str(tmp_path / "blurry_unsuitable.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="blurry_unsuitable.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.evidence_suitable is False
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_missing_evidence_routes_to_human_review(db_session, sample_complaint):
    # Complaint with zero evidence -> Assessment inconclusive, routes to REVIEW_REQUIRED
    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence_id=None)

    assert assessment.confidence_score is None
    assert assessment.evidence_suitable is False
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_corrupted_image_file_handled_safely(db_session, sample_complaint, tmp_path):
    # Corrupt unreadable binary file -> Caught by Pillow verify, routes to REVIEW_REQUIRED
    corrupt_path = str(tmp_path / "corrupt_data.jpg")
    create_corrupt_file(corrupt_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=corrupt_path,
        file_name="corrupt_data.jpg",
        file_size=os.path.getsize(corrupt_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.evidence_suitable is False
    assert assessment.confidence_score is None
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

# ============================================================================
# 4. Malformed Score & Output Sanitization
# ============================================================================

def test_malformed_confidence_score_sanitized_to_none(db_session, sample_complaint, tmp_path):
    # Malformed score (-0.5) from provider -> Must be sanitized to None, never converted to high confidence
    img_path = str(tmp_path / "malformed_score.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="malformed_score.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score is None
    assert assessment.review_required is True
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

# ============================================================================
# 5. Provider Exceptions and Timeouts Containment
# ============================================================================

def test_provider_timeout_handled_safely_without_crash(db_session, sample_complaint, tmp_path):
    # Simulated provider timeout -> Catches exception, records assessment, routes to REVIEW_REQUIRED
    img_path = str(tmp_path / "provider_timeout.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="provider_timeout.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score is None
    assert assessment.review_required is True
    assert "TimeoutError" in assessment.assessment_metadata.get("exception_type", "")
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

def test_provider_internal_exception_handled_safely(db_session, sample_complaint, tmp_path):
    # Simulated provider 500 error -> Recorded in metadata, complaint safe in REVIEW_REQUIRED
    img_path = str(tmp_path / "provider_error.jpg")
    create_valid_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=sample_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="provider_error.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg"
    )
    db_session.add(evidence)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    assessment, updated_complaint = service.assess_and_route(sample_complaint.id, evidence.id)

    assert assessment.confidence_score is None
    assert assessment.review_required is True
    assert "RuntimeError" in assessment.assessment_metadata.get("exception_type", "")
    assert updated_complaint.status == ComplaintStatus.REVIEW_REQUIRED

# ============================================================================
# 6. Evidence Ownership Mismatch
# ============================================================================

def test_evidence_ownership_mismatch_rejected(db_session, sample_complaint, sample_evidence):
    # Foreign evidence ID belonging to another complaint must be rejected with 400 Bad Request
    other_complaint = Complaint(
        reference_id="INFRA-OTHER-002",
        title="Other defect",
        category=ComplaintCategory.GARBAGE,
        description="Debris on sidewalk",
        status=ComplaintStatus.SUBMITTED
    )
    db_session.add(other_complaint)
    db_session.commit()

    service = IncidentAssessmentService(db_session)
    with pytest.raises(Exception) as exc_info:
        service.assess_and_route(other_complaint.id, evidence_id=sample_evidence.id)

    assert "does not belong to complaint" in str(exc_info.value)

# ============================================================================
# 7. Assessment History Preservation Across Retries
# ============================================================================

def test_assessment_history_preserved_across_retries(db_session, sample_complaint, sample_evidence):
    service = IncidentAssessmentService(db_session)

    # First attempt: blurry -> REVIEW_REQUIRED
    provider_blurry = DeterministicMockAssessmentProvider()
    service.provider = provider_blurry
    sample_complaint.title = "blurry photo initial report"
    db_session.commit()

    a1, c1 = service.assess_and_route(sample_complaint.id, sample_evidence.id)
    assert a1.confidence_score == 0.45
    assert c1.status == ComplaintStatus.REVIEW_REQUIRED

    # Second attempt / retry with clean photo -> AUTHORITY_QUEUE
    sample_complaint.title = "clear sharp pothole photo"
    db_session.commit()

    a2, c2 = service.assess_and_route(sample_complaint.id, sample_evidence.id)
    assert a2.confidence_score == 0.94
    assert c2.status == ComplaintStatus.AUTHORITY_QUEUE

    # Verify both assessments exist in database (history preserved!)
    history = service.get_assessments(sample_complaint.id)
    assert len(history) == 2
    assert history[0].id == a2.id
    assert history[1].id == a1.id

# ============================================================================
# 8. API Router Endpoints Verification
# ============================================================================

def test_api_assess_and_route_endpoint(client, sample_complaint, sample_evidence):
    headers = {"X-User-ID": sample_complaint.citizen_id}
    res = client.post(
        f"/api/complaints/{sample_complaint.id}/assessments?evidence_id={sample_evidence.id}",
        headers=headers
    )
    assert res.status_code == 201
    data = res.json()
    assert data["complaint_id"] == sample_complaint.id
    assert data["confidence_score"] == 0.94
    assert data["is_simulation"] is True

    # Check complaint status updated to AUTHORITY_QUEUE
    c_res = client.get(f"/api/complaints/{sample_complaint.id}")
    assert c_res.status_code == 200
    assert c_res.json()["status"] == "AUTHORITY_QUEUE"

    # Check list assessments endpoint
    list_res = client.get(
        f"/api/complaints/{sample_complaint.id}/assessments",
        headers=headers
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # Check get specific assessment endpoint
    aid = data["id"]
    get_res = client.get(
        f"/api/complaints/{sample_complaint.id}/assessments/{aid}",
        headers=headers
    )
    assert get_res.status_code == 200
    assert get_res.json()["id"] == aid
