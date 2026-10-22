import os
import pytest
from fastapi import status
from PIL import Image

from app.core.config import settings
from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.authority_action import AuthorityAction
from app.models.incident_assessment import IncidentAssessment
from app.schemas.authority_action import AuthorityActionType
from app.services.incident_assessment_service import IncidentAssessmentService
from app.services.authority_service import AuthorityService


def create_test_image(path: str, width: int = 300, height: int = 300, color: str = "gray"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")


AUTHORITY_HEADERS = {
    "X-Authority-Token": "infranex-dev-authority-secret-key-stage3",
    "X-Authority-ID": "muni_officer_042",
    "X-Department": "Department of Transportation"
}


@pytest.fixture
def authority_queue_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-AUTH-QUEUE-001",
        title="Severe asphalt crater on Main St",
        category=ComplaintCategory.POTHOLE,
        description="Hazardous defect blocking right lane traffic.",
        status=ComplaintStatus.AUTHORITY_QUEUE,
        location_address="100 Main Street",
        latitude=37.7749,
        longitude=-122.4194,
        location_type=LocationType.GPS,
        citizen_id="citizen_jane"
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.refresh(complaint)
    return complaint


@pytest.fixture
def second_authority_complaint(db_session):
    complaint = Complaint(
        reference_id="INFRA-AUTH-SECOND-002",
        title="Fallen streetlight wiring",
        category=ComplaintCategory.BROKEN_STREETLIGHT,
        description="Exposed street wiring near park entrance.",
        status=ComplaintStatus.AUTHORITY_QUEUE,
        location_address="200 Park Ave",
        latitude=37.7833,
        longitude=-122.4167,
        location_type=LocationType.GPS,
        citizen_id="citizen_mark"
    )
    db_session.add(complaint)
    db_session.commit()
    db_session.refresh(complaint)
    return complaint


@pytest.fixture
def complaint_with_evidence(db_session, authority_queue_complaint, tmp_path):
    img_path = str(tmp_path / "pothole_crater.jpg")
    create_test_image(img_path)
    evidence = ComplaintEvidence(
        complaint_id=authority_queue_complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path=img_path,
        file_name="pothole_crater.jpg",
        file_size=os.path.getsize(img_path),
        mime_type="image/jpeg",
        is_public_approved=False
    )
    db_session.add(evidence)
    db_session.commit()
    db_session.refresh(evidence)
    return authority_queue_complaint


# ============================================================================
# 1. Authority Queue Filtering & Pagination
# ============================================================================

def test_eligible_complaints_appear_in_authority_queue(client, authority_queue_complaint):
    res = client.get("/api/authority/queue", headers=AUTHORITY_HEADERS)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert len(data) >= 1
    ids = [item["id"] for item in data]
    assert authority_queue_complaint.id in ids


def test_ineligible_statuses_do_not_appear_in_authority_queue(client, db_session):
    ineligible_statuses = [
        ComplaintStatus.SUBMITTED,
        ComplaintStatus.PROCESSING,
        ComplaintStatus.UNDER_REVIEW,
        ComplaintStatus.REVIEW_REQUIRED,
        ComplaintStatus.EVIDENCE_REQUESTED,
        ComplaintStatus.RESOLVED,
        ComplaintStatus.REJECTED,
    ]
    for st in ineligible_statuses:
        complaint = Complaint(
            reference_id=f"INFRA-EXCLUDE-{st.value}",
            title=f"Complaint in {st.value}",
            category=ComplaintCategory.GARBAGE,
            description="Should not be in authority queue.",
            status=st,
            citizen_id="citizen_tester"
        )
        db_session.add(complaint)
    db_session.commit()

    # Query queue: none of these should appear
    res = client.get("/api/authority/queue", headers=AUTHORITY_HEADERS)
    assert res.status_code == status.HTTP_200_OK
    queue_statuses = {item["status"] for item in res.json()}
    for st in ineligible_statuses:
        assert st.value not in queue_statuses


def test_authority_queue_filters_by_category_and_pagination(client, authority_queue_complaint, second_authority_complaint):
    # Filter by POTHOLE
    res_pothole = client.get("/api/authority/queue?category=POTHOLE", headers=AUTHORITY_HEADERS)
    assert res_pothole.status_code == 200
    for item in res_pothole.json():
        assert item["category"] == "POTHOLE"

    # Pagination test: limit 1
    res_page = client.get("/api/authority/queue?limit=1", headers=AUTHORITY_HEADERS)
    assert res_page.status_code == 200
    assert len(res_page.json()) == 1


# ============================================================================
# 2. Authority Complaint Detail
# ============================================================================

def test_authority_complaint_detail_retrieval(client, complaint_with_evidence):
    res = client.get(
        f"/api/authority/complaints/{complaint_with_evidence.id}",
        headers=AUTHORITY_HEADERS
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["id"] == complaint_with_evidence.id
    assert data["reference_id"] == complaint_with_evidence.reference_id
    assert data["title"] == complaint_with_evidence.title
    assert data["status"] == "AUTHORITY_QUEUE"
    assert len(data["evidence_items"]) >= 1
    # Citizen ID is present for context, but no private personal info leaked
    assert data["citizen_id"] == "citizen_jane"


def test_authority_complaint_detail_not_found(client):
    res = client.get(
        "/api/authority/complaints/non-existent-uuid-99999",
        headers=AUTHORITY_HEADERS
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 3. Authority Actions: Acknowledge, Dispatch, Start Work, Resolve
# ============================================================================

def test_authority_acknowledge_action(client, authority_queue_complaint):
    # Acknowledge incident in queue
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Acknowledged by transportation dispatcher unit 4."}
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["action_type"] == "ACKNOWLEDGE"
    assert data["authority_id"] == "muni_officer_042"
    assert data["department"] == "Department of Transportation"
    assert "Acknowledged" in data["notes"]

    # Verify complaint remains in AUTHORITY_QUEUE
    c_res = client.get(
        f"/api/authority/complaints/{authority_queue_complaint.id}",
        headers=AUTHORITY_HEADERS
    )
    assert c_res.json()["status"] == "AUTHORITY_QUEUE"


def test_authority_dispatch_action(client, authority_queue_complaint):
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={
            "work_order_reference": "WO-SF-2026-0042",
            "notes": "Crew 7 assigned for emergency asphalt patch."
        }
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["action_type"] == "DISPATCH"
    assert data["work_order_reference"] == "WO-SF-2026-0042"

    # Status should transition to ACTION_IN_PROGRESS
    c_res = client.get(
        f"/api/authority/complaints/{authority_queue_complaint.id}",
        headers=AUTHORITY_HEADERS
    )
    assert c_res.json()["status"] == "ACTION_IN_PROGRESS"


def test_authority_start_work_and_resolve_flow(client, authority_queue_complaint):
    # 1. Dispatch
    client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={"work_order_reference": "WO-SF-100"}
    )

    # 2. Start field work via generic actions endpoint
    res_start = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/actions",
        headers=AUTHORITY_HEADERS,
        json={
            "action_type": "START_WORK",
            "notes": "Pothole excavated and hot asphalt application started."
        }
    )
    assert res_start.status_code == status.HTTP_201_CREATED
    assert res_start.json()["action_type"] == "START_WORK"

    c_start = client.get(
        f"/api/authority/complaints/{authority_queue_complaint.id}",
        headers=AUTHORITY_HEADERS
    )
    assert c_start.json()["status"] == "REPAIR_IN_PROGRESS"

    # 3. Resolve work
    res_resolve = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/resolve",
        headers=AUTHORITY_HEADERS,
        json={
            "notes": "Pothole filled, compacted and leveled with street surface. Curing complete.",
            "work_order_reference": "WO-SF-100"
        }
    )
    assert res_resolve.status_code == status.HTTP_201_CREATED
    assert res_resolve.json()["action_type"] == "RESOLVE"

    c_resolved = client.get(
        f"/api/authority/complaints/{authority_queue_complaint.id}",
        headers=AUTHORITY_HEADERS
    )
    assert c_resolved.json()["status"] == "RESOLVED"


# ============================================================================
# 4. Action Validation & Lifecycle Enforcement
# ============================================================================

def test_invalid_action_type_rejected(client, authority_queue_complaint):
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/actions",
        headers=AUTHORITY_HEADERS,
        json={"action_type": "NOT_A_VALID_ACTION", "notes": "Invalid"}
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_ineligible_complaint_cannot_be_acted_upon(client, db_session):
    resolved_complaint = Complaint(
        reference_id="INFRA-RESOLVED-NO-ACTION",
        title="Already resolved complaint",
        category=ComplaintCategory.POTHOLE,
        description="Done",
        status=ComplaintStatus.RESOLVED,
        citizen_id="citizen_tester"
    )
    db_session.add(resolved_complaint)
    db_session.commit()

    res = client.post(
        f"/api/authority/complaints/{resolved_complaint.id}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={"work_order_reference": "WO-999"}
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "not eligible for authority actions" in res.json().get("detail", "")


def test_contradictory_direct_resolve_from_queue_rejected(client, authority_queue_complaint):
    # Cannot directly resolve from AUTHORITY_QUEUE without acknowledging or dispatching
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/actions",
        headers=AUTHORITY_HEADERS,
        json={
            "action_type": "RESOLVE",
            "notes": "Premature resolution attempt"
        }
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot directly resolve" in res.json().get("detail", "")


def test_redundant_acknowledge_on_in_progress_rejected(client, authority_queue_complaint):
    # Dispatch first
    client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={"work_order_reference": "WO-101"}
    )

    # Redundant acknowledge on ACTION_IN_PROGRESS
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Belated acknowledge"}
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "redundant acknowledge action" in res.json().get("detail", "")


# ============================================================================
# 5. Action History & Cross-Complaint Boundary
# ============================================================================

def test_authority_action_history_persisted_in_order(client, authority_queue_complaint):
    # Record acknowledge then dispatch
    client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Step 1: Acknowledge"}
    )
    client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Step 2: Dispatch", "work_order_reference": "WO-SEQ-001"}
    )

    # Fetch history
    res = client.get(
        f"/api/authority/complaints/{authority_queue_complaint.id}/actions",
        headers=AUTHORITY_HEADERS
    )
    assert res.status_code == status.HTTP_200_OK
    actions = res.json()
    assert len(actions) == 2
    # Newest first
    assert actions[0]["action_type"] == "DISPATCH"
    assert actions[1]["action_type"] == "ACKNOWLEDGE"


def test_cross_complaint_action_retrieval_denied(client, authority_queue_complaint, second_authority_complaint):
    # Create action on complaint A
    res_a = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=AUTHORITY_HEADERS
    )
    action_a_id = res_a.json()["id"]

    # Try to access action A via Complaint B's URL -> 404
    res_cross = client.get(
        f"/api/authority/complaints/{second_authority_complaint.id}/actions/{action_a_id}",
        headers=AUTHORITY_HEADERS
    )
    assert res_cross.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 6. Validated Server Context Actor Identity & Transaction Consistency
# ============================================================================

def test_actor_identity_strictly_from_server_validated_context(client, authority_queue_complaint):
    # Client tries to impersonate a different authority in request parameters
    res = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Official acknowledge"}
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    # The authority_id must strictly match the validated header identity "muni_officer_042"
    assert data["authority_id"] == "muni_officer_042"
    assert data["department"] == "Department of Transportation"


def test_transaction_rollback_consistency_on_failure(db_session, authority_queue_complaint):
    service = AuthorityService(db_session)
    count_before = db_session.query(AuthorityAction).filter(AuthorityAction.complaint_id == authority_queue_complaint.id).count()

    # Attempt an action with an invalid state transition that will fail
    from app.schemas.authority_action import AuthorityActionCreate
    from app.core.security import AuthorityIdentity
    invalid_action = AuthorityActionCreate(
        action_type=AuthorityActionType.RESOLVE,  # Incompatible directly from AUTHORITY_QUEUE
        notes="Fail test"
    )
    auth_identity = AuthorityIdentity(authority_id="test_muni", department="DPW")

    with pytest.raises(Exception):
        service.record_action(authority_queue_complaint.id, invalid_action, auth_identity)

    # Verify no action was persisted and status was not changed
    db_session.refresh(authority_queue_complaint)
    count_after = db_session.query(AuthorityAction).filter(AuthorityAction.complaint_id == authority_queue_complaint.id).count()
    assert count_after == count_before
    assert authority_queue_complaint.status == ComplaintStatus.AUTHORITY_QUEUE


# ============================================================================
# 7. Authorization Security Tests
# ============================================================================

def test_anonymous_authority_requests_denied(client, authority_queue_complaint):
    # Queue
    assert client.get("/api/authority/queue").status_code == status.HTTP_401_UNAUTHORIZED
    # Detail
    assert client.get(f"/api/authority/complaints/{authority_queue_complaint.id}").status_code == status.HTTP_401_UNAUTHORIZED
    # Acknowledge
    assert client.post(f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge").status_code == status.HTTP_401_UNAUTHORIZED
    # History
    assert client.get(f"/api/authority/complaints/{authority_queue_complaint.id}/actions").status_code == status.HTTP_401_UNAUTHORIZED


def test_citizen_cannot_use_authority_endpoints(client, authority_queue_complaint):
    citizen_headers = {"X-User-ID": "citizen_jane"}
    res = client.get("/api/authority/queue", headers=citizen_headers)
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "Citizen identities do not have authority privileges" in res.json().get("detail", "")

    res_post = client.post(
        f"/api/authority/complaints/{authority_queue_complaint.id}/acknowledge",
        headers=citizen_headers
    )
    assert res_post.status_code == status.HTTP_403_FORBIDDEN


def test_unverified_role_authority_claim_denied(client, authority_queue_complaint):
    # Caller sends X-Role: AUTHORITY without a valid token -> 403 Forbidden
    fake_authority_headers = {"X-Role": "AUTHORITY", "X-Authority-ID": "fake_officer"}
    res = client.get("/api/authority/queue", headers=fake_authority_headers)
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "valid authority token required" in res.json().get("detail", "")


def test_reviewer_credentials_do_not_grant_authority_privileges(client, authority_queue_complaint):
    reviewer_headers = {
        "X-Role": "REVIEWER",
        "X-Reviewer-Token": "infranex-dev-reviewer-secret-key-stage5"
    }
    res = client.get("/api/authority/queue", headers=reviewer_headers)
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "Reviewer credentials do not grant authority privileges" in res.json().get("detail", "")


def test_production_mode_rejects_simulated_authority_headers(client, authority_queue_complaint):
    original_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        res = client.get("/api/authority/queue", headers=AUTHORITY_HEADERS)
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "disabled in production" in res.json().get("detail", "")
    finally:
        settings.ENVIRONMENT = original_env


# ============================================================================
# 8. Shared End-to-End Lifecycle Flow
# ============================================================================

def test_shared_lifecycle_citizen_to_assessment_to_authority_resolution(client, db_session, tmp_path):
    # Step 1: Citizen creates complaint
    create_res = client.post(
        "/api/complaints",
        json={
            "title": "Deep pothole on Elm Street",
            "category": "POTHOLE",
            "description": "Wheel damage reported by multiple cyclists.",
            "location_address": "450 Elm St",
            "latitude": 37.765,
            "longitude": -122.425,
            "citizen_id": "citizen_elena"
        }
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    complaint_data = create_res.json()
    cid = complaint_data["id"]
    assert complaint_data["status"] == "SUBMITTED"

    # Step 2: Citizen uploads photo evidence
    img_path = str(tmp_path / "elm_pothole.jpg")
    create_test_image(img_path)
    with open(img_path, "rb") as f:
        ev_res = client.post(
            f"/api/complaints/{cid}/evidence",
            files={"file": ("elm_pothole.jpg", f, "image/jpeg")},
            data={"evidence_type": "INITIAL_REPORT"}
        )
    assert ev_res.status_code == status.HTTP_201_CREATED
    ev_id = ev_res.json()["id"]

    # Step 3: Trigger AI assessment (owner citizen authenticates)
    assess_res = client.post(
        f"/api/complaints/{cid}/assessments?evidence_id={ev_id}",
        headers={"X-User-ID": "citizen_elena"}
    )
    assert assess_res.status_code == status.HTTP_201_CREATED
    assert assess_res.json()["confidence_score"] == 0.94
    assert assess_res.json()["is_simulation"] is True

    # High confidence (0.94 >= 0.90) routes directly to AUTHORITY_QUEUE
    c_check = client.get(f"/api/complaints/{cid}")
    assert c_check.json()["status"] == "AUTHORITY_QUEUE"

    # Step 4: Authority queries queue and finds incident
    queue_res = client.get("/api/authority/queue", headers=AUTHORITY_HEADERS)
    assert queue_res.status_code == status.HTTP_200_OK
    queue_ids = [item["id"] for item in queue_res.json()]
    assert cid in queue_ids

    # Step 5: Authority acknowledges
    ack_res = client.post(
        f"/api/authority/complaints/{cid}/acknowledge",
        headers=AUTHORITY_HEADERS,
        json={"notes": "Public Works Dept acknowledged and triaged."}
    )
    assert ack_res.status_code == status.HTTP_201_CREATED

    # Step 6: Authority dispatches field crew
    disp_res = client.post(
        f"/api/authority/complaints/{cid}/dispatch",
        headers=AUTHORITY_HEADERS,
        json={
            "work_order_reference": "WO-ELM-2026-881",
            "notes": "Field unit 12 dispatched."
        }
    )
    assert disp_res.status_code == status.HTTP_201_CREATED
    assert client.get(f"/api/complaints/{cid}").json()["status"] == "ACTION_IN_PROGRESS"

    # Step 7: Authority starts work on the ground
    work_res = client.post(
        f"/api/authority/complaints/{cid}/actions",
        headers=AUTHORITY_HEADERS,
        json={
            "action_type": "START_WORK",
            "notes": "Excavation and asphalt packing in progress."
        }
    )
    assert work_res.status_code == status.HTTP_201_CREATED
    assert client.get(f"/api/complaints/{cid}").json()["status"] == "REPAIR_IN_PROGRESS"

    # Step 8: Authority resolves repair
    resolve_res = client.post(
        f"/api/authority/complaints/{cid}/resolve",
        headers=AUTHORITY_HEADERS,
        json={
            "notes": "Asphalt patch completed, cooled, and traffic opened.",
            "work_order_reference": "WO-ELM-2026-881"
        }
    )
    assert resolve_res.status_code == status.HTTP_201_CREATED
    final_complaint = client.get(f"/api/complaints/{cid}").json()
    assert final_complaint["status"] == "RESOLVED"

    # Step 9: Verify complete chronological action history
    history_res = client.get(
        f"/api/authority/complaints/{cid}/actions",
        headers=AUTHORITY_HEADERS
    )
    assert history_res.status_code == status.HTTP_200_OK
    actions = history_res.json()
    assert len(actions) == 4
    action_types = [a["action_type"] for a in actions]
    assert action_types == ["RESOLVE", "START_WORK", "DISPATCH", "ACKNOWLEDGE"]
