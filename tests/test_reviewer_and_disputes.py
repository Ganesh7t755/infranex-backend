import pytest
from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.models.dispute import DisputeStatus
from app.models.review_decision import ReviewDecisionAction

REVIEWER_HEADERS = {"X-Role": "REVIEWER", "X-Reviewer-ID": "test_lead_reviewer"}

def create_sample_complaint(client, citizen_id="citizen_alice", category="POTHOLE"):
    res = client.post("/api/complaints", json={
        "title": "Damaged Roadway on Main St",
        "category": category,
        "description": "Hazardous asphalt breakdown near pedestrian crosswalk.",
        "location_address": "123 Main Street",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "citizen_id": citizen_id
    })
    assert res.status_code == 201
    return res.json()

def advance_to_verification_pending(client, complaint_id):
    # SUBMITTED -> UNDER_REVIEW -> REPAIR_IN_PROGRESS -> REPAIR_CLAIMED -> VERIFICATION_PENDING
    client.patch(f"/api/complaints/{complaint_id}/status", json={"new_status": "UNDER_REVIEW"})
    client.patch(f"/api/complaints/{complaint_id}/status", json={"new_status": "REPAIR_IN_PROGRESS"})
    client.patch(f"/api/complaints/{complaint_id}/status", json={"new_status": "REPAIR_CLAIMED"})
    res = client.patch(f"/api/complaints/{complaint_id}/status", json={"new_status": "VERIFICATION_PENDING"})
    assert res.status_code == 200
    assert res.json()["status"] == "VERIFICATION_PENDING"

def test_unauthorized_reviewer_actions(client):
    # Without reviewer headers or token, queue access should be forbidden (403)
    unauthorized_res = client.get("/api/reviewer/queue")
    assert unauthorized_res.status_code == 403
    assert "Reviewer authorization required" in unauthorized_res.json()["detail"]

    # Client-asserted X-User-ID alone must NOT grant reviewer access
    arbitrary_user_res = client.get(
        "/api/reviewer/queue",
        headers={"X-User-ID": "random_attacker"}
    )
    assert arbitrary_user_res.status_code == 403

def test_reviewer_queue_retrieval_and_filtering(client):
    c1 = create_sample_complaint(client, citizen_id="citizen_1", category="POTHOLE")
    c2 = create_sample_complaint(client, citizen_id="citizen_2", category="GARBAGE")

    # Advance c2 to VERIFICATION_PENDING
    advance_to_verification_pending(client, c2["id"])

    # Query queue with valid reviewer identity
    queue_res = client.get("/api/reviewer/queue", headers=REVIEWER_HEADERS)
    assert queue_res.status_code == 200
    items = queue_res.json()
    assert len(items) >= 2

    # Filter by category
    pothole_queue = client.get("/api/reviewer/queue?category=POTHOLE", headers=REVIEWER_HEADERS).json()
    assert all(i["category"] == "POTHOLE" for i in pothole_queue)

    # Filter by review_state
    pending_v = client.get("/api/reviewer/queue?review_state=PENDING_VERIFICATION", headers=REVIEWER_HEADERS).json()
    assert any(i["id"] == c2["id"] for i in pending_v)

def test_reviewer_queue_includes_review_required_status(client):
    # 1. Create a complaint and transition to REVIEW_REQUIRED
    c_rev = create_sample_complaint(client, citizen_id="citizen_review_test", category="POTHOLE")
    c_id = c_rev["id"]
    client.patch(
        f"/api/complaints/{c_id}/status",
        headers={"X-Role": "REVIEWER"},
        json={"new_status": "REVIEW_REQUIRED", "notes": "Low AI confidence routed to human reviewer."}
    )

    # 2. Verify it appears in the default reviewer queue (without status filter)
    default_queue = client.get("/api/reviewer/queue", headers=REVIEWER_HEADERS).json()
    matching = [i for i in default_queue if i["id"] == c_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "REVIEW_REQUIRED"
    assert matching[0]["review_state"] == "NEEDS_REVIEW"

    # 3. Explicit status filter works
    rev_req_queue = client.get("/api/reviewer/queue?status=REVIEW_REQUIRED", headers=REVIEWER_HEADERS).json()
    assert any(i["id"] == c_id for i in rev_req_queue)
    assert all(i["status"] == "REVIEW_REQUIRED" for i in rev_req_queue)

    # 4. Review state filter works
    needs_rev_queue = client.get("/api/reviewer/queue?review_state=NEEDS_REVIEW", headers=REVIEWER_HEADERS).json()
    assert any(i["id"] == c_id for i in needs_rev_queue)

    # 5. Non-review statuses (e.g. AUTHORITY_QUEUE, RESOLVED) do not appear in default queue
    c_auth = create_sample_complaint(client, citizen_id="citizen_auth_test")
    client.patch(
        f"/api/complaints/{c_auth['id']}/status",
        headers={"X-Role": "REVIEWER"},
        json={"new_status": "REVIEW_REQUIRED"}
    )
    client.patch(
        f"/api/complaints/{c_auth['id']}/status",
        headers={"X-Role": "REVIEWER"},
        json={"new_status": "VERIFIED"}
    )
    client.patch(
        f"/api/complaints/{c_auth['id']}/status",
        headers={"X-Role": "REVIEWER"},
        json={"new_status": "AUTHORITY_QUEUE"}
    )
    current_queue = client.get("/api/reviewer/queue", headers=REVIEWER_HEADERS).json()
    assert not any(i["id"] == c_auth["id"] for i in current_queue)

    # 6. Authorization boundary preserved
    assert client.get("/api/reviewer/queue").status_code == 403
    assert client.get("/api/reviewer/queue", headers={"X-User-ID": "citizen_review_test"}).status_code == 403

def test_reviewer_decision_confirm_repair(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_target")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    # Submit official reviewer decision: CONFIRM_REPAIR
    decision_payload = {
        "action": "CONFIRM_REPAIR",
        "reason": "Before and after evidence confirms asphalt has been fully leveled and sealed.",
        "notes": "Verified by municipal inspector team 4."
    }
    decision_res = client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json=decision_payload,
        headers=REVIEWER_HEADERS
    )
    assert decision_res.status_code == 201
    decision_data = decision_res.json()
    assert decision_data["action"] == "CONFIRM_REPAIR"
    assert decision_data["previous_status"] == "VERIFICATION_PENDING"
    assert decision_data["new_status"] == "RESOLVED_AFTER_REVIEW"
    assert decision_data["reviewer_id"] == "test_lead_reviewer"
    assert decision_data["is_simulation"] is True

    # Verify complaint status updated
    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "RESOLVED_AFTER_REVIEW"

    # Verify timeline event appended
    timeline = client.get(f"/api/complaints/{c_id}/timeline").json()
    latest_event = timeline[-1]
    assert latest_event["new_status"] == "RESOLVED_AFTER_REVIEW"
    assert latest_event["actor_type"] == "REVIEWER"
    assert latest_event["actor_id"] == "test_lead_reviewer"
    assert "Official Decision: CONFIRM_REPAIR" in latest_event["notes"]

    # Verify notification generated for citizen
    notif_res = client.get("/api/notifications", headers={"X-User-ID": "citizen_target"})
    assert notif_res.status_code == 200
    notifications = notif_res.json()["items"]
    assert any(n["complaint_id"] == c_id and "Resolved" in n["title"] for n in notifications)

def test_reviewer_decision_request_rework(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_rework")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    decision_payload = {
        "action": "REQUEST_REWORK",
        "reason": "Repair patch is uneven and edges have already started peeling.",
        "notes": "Contractor must re-mill the section."
    }
    decision_res = client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json=decision_payload,
        headers=REVIEWER_HEADERS
    )
    assert decision_res.status_code == 201
    assert decision_res.json()["new_status"] == "REWORK_REQUESTED"

    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "REWORK_REQUESTED"

def test_reviewer_decision_request_evidence(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_ev")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    decision_payload = {
        "action": "REQUEST_EVIDENCE",
        "reason": "Submitted after-photo is blurry and does not clearly display the repair patch.",
        "notes": "Request high-resolution daytime photo."
    }
    decision_res = client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json=decision_payload,
        headers=REVIEWER_HEADERS
    )
    assert decision_res.status_code == 201
    assert decision_res.json()["new_status"] == "EVIDENCE_REQUESTED"

    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "EVIDENCE_REQUESTED"

def test_reviewer_decision_rejects_invalid_transition(client):
    complaint = create_sample_complaint(client)
    c_id = complaint["id"]
    # Complaint is currently in SUBMITTED
    # Attempting to confirm repair directly from SUBMITTED must fail (400)
    decision_res = client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={
            "action": "CONFIRM_REPAIR",
            "reason": "Illegal transition attempt"
        },
        headers=REVIEWER_HEADERS
    )
    assert decision_res.status_code == 400
    assert "Invalid state transition" in decision_res.json()["detail"]

def test_citizen_dispute_submission_valid(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_alice")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    # First resolve the complaint
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={
            "action": "CONFIRM_REPAIR",
            "reason": "Initial inspector marked as fixed."
        },
        headers=REVIEWER_HEADERS
    )

    # Alice files a dispute
    dispute_payload = {
        "reason": "The pothole was only filled with loose gravel which washed away after rain this morning.",
    }
    dispute_res = client.post(
        f"/api/complaints/{c_id}/disputes",
        json=dispute_payload,
        headers={"X-User-ID": "citizen_alice"}
    )
    assert dispute_res.status_code == 201
    dispute_data = dispute_res.json()
    assert dispute_data["status"] == "PENDING_REVIEW"
    assert dispute_data["citizen_id"] == "citizen_alice"
    assert dispute_data["complaint_id"] == c_id
    assert "loose gravel" in dispute_data["reason"]

    # Complaint status transitions to DISPUTED
    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "DISPUTED"

    # Timeline includes dispute submission
    timeline = client.get(f"/api/complaints/{c_id}/timeline").json()
    assert any(e["new_status"] == "DISPUTED" and e["actor_type"] == "CITIZEN" for e in timeline)

def test_citizen_dispute_ownership_check(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_owner")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Confirmed repaired"},
        headers=REVIEWER_HEADERS
    )

    # Different citizen attempts to dispute
    unauthorized_res = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Attempting to dispute someone else's complaint"},
        headers={"X-User-ID": "citizen_intruder"}
    )
    assert unauthorized_res.status_code == 403
    assert "Citizen authorization failure" in unauthorized_res.json()["detail"]

def test_citizen_dispute_validation_and_duplicate_handling(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_dup")
    c_id = complaint["id"]

    # Attempting to dispute while SUBMITTED (not resolved) must fail with 400
    early_dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Premature dispute reason"},
        headers={"X-User-ID": "citizen_dup"}
    )
    assert early_dispute.status_code == 400
    assert "RESOLVED_AFTER_REVIEW" in early_dispute.json()["detail"]

    # Resolve complaint
    advance_to_verification_pending(client, c_id)
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Repaired"},
        headers=REVIEWER_HEADERS
    )

    # Dispute with too short reason fails with 422
    short_reason = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "No"},
        headers={"X-User-ID": "citizen_dup"}
    )
    assert short_reason.status_code == 422

    # First valid dispute succeeds
    first_dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Valid detailed reason for dispute"},
        headers={"X-User-ID": "citizen_dup"}
    )
    assert first_dispute.status_code == 201

    # Immediate second dispute while first is PENDING_REVIEW must be rejected with 409 Conflict
    dup_dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Another dispute while one is already pending"},
        headers={"X-User-ID": "citizen_dup"}
    )
    assert dup_dispute.status_code == 409
    assert "already pending review" in dup_dispute.json()["detail"]

def test_reviewer_resolve_dispute_upheld(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_upheld")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Fixed"},
        headers=REVIEWER_HEADERS
    )
    dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Problem still exists exactly as before."},
        headers={"X-User-ID": "citizen_upheld"}
    ).json()

    dispute_id = dispute["id"]

    # Reviewer upholds dispute: citizen was right, issue remains unresolved -> rework ordered
    resolve_res = client.post(
        f"/api/reviewer/complaints/{c_id}/disputes/{dispute_id}/resolve",
        json={
            "outcome": "UPHELD",
            "reviewer_notes": "Field inspection re-check verified asphalt patch failed. Ordering rework."
        },
        headers=REVIEWER_HEADERS
    )
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["status"] == "UPHELD"
    assert res_data["reviewer_id"] == "test_lead_reviewer"
    assert res_data["resolved_at"] is not None

    # Complaint moves to REWORK_REQUESTED
    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "REWORK_REQUESTED"

def test_reviewer_resolve_dispute_overturned(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_overturned")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Fixed"},
        headers=REVIEWER_HEADERS
    )
    dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "I do not agree with the repair."},
        headers={"X-User-ID": "citizen_overturned"}
    ).json()

    dispute_id = dispute["id"]

    # Reviewer overturns dispute: resolution was correct, complaint marked REASSESSMENT_COMPLETED
    resolve_res = client.post(
        f"/api/reviewer/complaints/{c_id}/disputes/{dispute_id}/resolve",
        json={
            "outcome": "OVERTURNED",
            "reviewer_notes": "Engineer confirmed the work meets municipal civil engineering standards."
        },
        headers=REVIEWER_HEADERS
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "OVERTURNED"

    detail = client.get(f"/api/complaints/{c_id}").json()
    assert detail["status"] == "REASSESSMENT_COMPLETED"

def test_history_preservation_across_decisions_and_disputes(client):
    complaint = create_sample_complaint(client, citizen_id="citizen_hist")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    # Initial decision
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Initial resolution reason"},
        headers=REVIEWER_HEADERS
    )

    # Citizen dispute
    dispute = client.post(
        f"/api/complaints/{c_id}/disputes",
        json={"reason": "Citizen dispute reason"},
        headers={"X-User-ID": "citizen_hist"}
    ).json()

    # Reviewer resolve dispute
    client.post(
        f"/api/reviewer/complaints/{c_id}/disputes/{dispute['id']}/resolve",
        json={"outcome": "UPHELD", "reviewer_notes": "Upholding dispute and ordering rework"},
        headers=REVIEWER_HEADERS
    )

    # Fetch complaint detail and review decisions
    decisions = client.get(f"/api/reviewer/complaints/{c_id}/decisions", headers=REVIEWER_HEADERS).json()
    assert len(decisions) >= 1
    assert decisions[0]["reason"] == "Initial resolution reason"

    # Verify disputes history
    disputes = client.get(f"/api/complaints/{c_id}/disputes").json()
    assert len(disputes) == 1
    assert disputes[0]["status"] == "UPHELD"
    assert disputes[0]["reason"] == "Citizen dispute reason"

    # Timeline preserves all chronological events
    timeline = client.get(f"/api/complaints/{c_id}/timeline").json()
    event_statuses = [e["new_status"] for e in timeline]
    assert "SUBMITTED" in event_statuses
    assert "UNDER_REVIEW" in event_statuses
    assert "REPAIR_IN_PROGRESS" in event_statuses
    assert "REPAIR_CLAIMED" in event_statuses
    assert "VERIFICATION_PENDING" in event_statuses
    assert "RESOLVED_AFTER_REVIEW" in event_statuses
    assert "DISPUTED" in event_statuses
    assert "REWORK_REQUESTED" in event_statuses

def test_production_reviewer_operations_strictly_disabled(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    
    # Even with reviewer headers, production environment rejects reviewer operations
    res = client.get("/api/reviewer/queue", headers=REVIEWER_HEADERS)
    assert res.status_code == 403
    assert "Production reviewer operations are disabled until Stage 7" in res.json()["detail"]


def test_citizen_can_read_complaint_decisions_without_403(client):
    """
    Verifies that when a citizen or client views complaint details,
    reading official review decisions succeeds (HTTP 200) instead of throwing 403 Forbidden.
    """
    complaint = create_sample_complaint(client, citizen_id="citizen_detail_viewer")
    c_id = complaint["id"]
    advance_to_verification_pending(client, c_id)

    # Reviewer creates a decision
    client.post(
        f"/api/reviewer/complaints/{c_id}/decide",
        json={"action": "CONFIRM_REPAIR", "reason": "Repair inspected and confirmed"},
        headers=REVIEWER_HEADERS
    )

    # 1. Citizen header X-Role: CITIZEN on /api/reviewer/complaints/{id}/decisions must return 200 (not 403)
    res_citizen = client.get(
        f"/api/reviewer/complaints/{c_id}/decisions",
        headers={"X-Role": "CITIZEN", "X-User-ID": "citizen_detail_viewer"}
    )
    assert res_citizen.status_code == 200
    decisions_list = res_citizen.json()
    assert len(decisions_list) >= 1
    assert decisions_list[0]["action"] == "CONFIRM_REPAIR"

    # 2. Public /api/complaints/{id}/decisions endpoint also works without headers
    res_public = client.get(f"/api/complaints/{c_id}/decisions")
    assert res_public.status_code == 200
    assert len(res_public.json()) >= 1


