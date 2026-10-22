import io
import os
import pytest

def create_sample_complaint(client, title="Large pothole on 4th St", category="POTHOLE"):
    res = client.post("/api/complaints", json={
        "title": title,
        "category": category,
        "description": "Deep asphalt crater causing vehicle alignment issues.",
        "location_address": "4th St & Mission",
        "latitude": 37.7858,
        "longitude": -122.4065,
        "location_type": "GPS",
        "citizen_id": "citizen_tester"
    })
    assert res.status_code == 201
    return res.json()

def upload_evidence_for_complaint(client, complaint_id, filename="photo.jpg", evidence_type="INITIAL_REPORT", content=None):
    if content is None:
        content = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 500
    file_bytes = io.BytesIO(content)
    res = client.post(
        f"/api/complaints/{complaint_id}/evidence",
        files={"file": (filename, file_bytes, "image/jpeg")},
        data={"evidence_type": evidence_type}
    )
    assert res.status_code == 201
    return res.json()

def test_verification_likely_resolved(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    # Attach initial report evidence
    before_ev = upload_evidence_for_complaint(client, cid, "before_pothole.jpg", "INITIAL_REPORT")
    # Attach repair claim evidence
    after_ev = upload_evidence_for_complaint(client, cid, "after_repaired.jpg", "REPAIR_CLAIM")

    # Request verification
    res = client.post(
        f"/api/complaints/{cid}/verifications",
        json={
            "before_evidence_id": before_ev["id"],
            "after_evidence_id": after_ev["id"]
        }
    )
    assert res.status_code == 201
    data = res.json()

    assert data["outcome"] == "LIKELY_RESOLVED"
    assert "remediated" in data["explanation"].lower() or "addressed" in data["explanation"].lower()
    assert len(data["observations"]) >= 2
    assert data["is_simulation"] is True
    assert data["human_review_required"] is True
    assert data["provider_id"] == "mock_deterministic_v1"
    assert data["model_name"] == "infranex-heuristic-simulator-v1"
    assert data["before_evidence_id"] == before_ev["id"]
    assert data["after_evidence_id"] == after_ev["id"]

    # Verify official complaint status did NOT change
    c_after = client.get(f"/api/complaints/{cid}").json()
    assert c_after["status"] == complaint["status"]

    # Verify audit event in timeline
    timeline = client.get(f"/api/complaints/{cid}/timeline").json()
    ai_event = next((e for e in timeline if e["actor_id"] == "ai_repair_verifier" or "AI Repair Verification" in (e.get("notes") or "")), None)
    assert ai_event is not None
    assert "LIKELY_RESOLVED" in ai_event["notes"]
    assert ai_event["actor_type"] == "SYSTEM"

def test_verification_likely_unresolved(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    before_ev = upload_evidence_for_complaint(client, cid, "before_pothole.jpg", "INITIAL_REPORT")
    # Use after evidence with 'unresolved' in filename to trigger unresolved simulation rule
    after_ev = upload_evidence_for_complaint(client, cid, "after_unresolved_patch.jpg", "REPAIR_CLAIM")

    res = client.post(
        f"/api/complaints/{cid}/verifications",
        json={
            "before_evidence_id": before_ev["id"],
            "after_evidence_id": after_ev["id"]
        }
    )
    assert res.status_code == 201
    data = res.json()

    assert data["outcome"] == "LIKELY_UNRESOLVED"
    assert "incomplete" in data["explanation"].lower() or "residual" in data["explanation"].lower()
    assert data["human_review_required"] is True

def test_verification_inconclusive_due_to_blurry_evidence(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    before_ev = upload_evidence_for_complaint(client, cid, "before_pothole.jpg", "INITIAL_REPORT")
    # Use after evidence with 'blurry' in filename to trigger inconclusive simulation rule
    after_ev = upload_evidence_for_complaint(client, cid, "after_blurry_camera.jpg", "REPAIR_CLAIM")

    res = client.post(
        f"/api/complaints/{cid}/verifications",
        json={
            "before_evidence_id": before_ev["id"],
            "after_evidence_id": after_ev["id"]
        }
    )
    assert res.status_code == 201
    data = res.json()

    assert data["outcome"] == "INCONCLUSIVE"
    assert "inadequate" in data["explanation"].lower() or "cannot" in data["explanation"].lower()

def test_verification_inconclusive_when_missing_after_evidence(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    # Only attach before evidence, no after evidence
    before_ev = upload_evidence_for_complaint(client, cid, "only_before.jpg", "INITIAL_REPORT")

    res = client.post(f"/api/complaints/{cid}/verifications", json={})
    assert res.status_code == 201
    data = res.json()

    assert data["outcome"] == "INCONCLUSIVE"
    assert "missing" in data["explanation"].lower()
    assert "post-repair" in data["explanation"].lower() or "claimed" in data["explanation"].lower()

def test_verification_cross_complaint_evidence_rejected(client):
    # Create two separate complaints
    c1 = create_sample_complaint(client, title="Issue One")
    c2 = create_sample_complaint(client, title="Issue Two")

    ev1 = upload_evidence_for_complaint(client, c1["id"], "ev1.jpg", "INITIAL_REPORT")
    ev2 = upload_evidence_for_complaint(client, c2["id"], "ev2.jpg", "REPAIR_CLAIM")

    # Attempt to verify c1 using ev2 which belongs to c2
    res = client.post(
        f"/api/complaints/{c1['id']}/verifications",
        json={
            "before_evidence_id": ev1["id"],
            "after_evidence_id": ev2["id"]
        }
    )
    assert res.status_code == 400
    assert "does not belong to complaint" in res.json()["detail"]

def test_verification_missing_file_on_storage(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    before_ev = upload_evidence_for_complaint(client, cid, "before.jpg", "INITIAL_REPORT")
    after_ev = upload_evidence_for_complaint(client, cid, "after.jpg", "REPAIR_CLAIM")

    # Remove after evidence file from disk using actual file_path
    if os.path.exists(after_ev["file_path"]):
        os.remove(after_ev["file_path"])

    res = client.post(
        f"/api/complaints/{cid}/verifications",
        json={
            "before_evidence_id": before_ev["id"],
            "after_evidence_id": after_ev["id"]
        }
    )
    assert res.status_code == 201
    data = res.json()
    assert data["outcome"] == "INCONCLUSIVE"
    assert "storage" in data["explanation"].lower() or "accessed" in data["explanation"].lower()

def test_verification_history_and_get_by_id(client):
    complaint = create_sample_complaint(client)
    cid = complaint["id"]

    before_ev = upload_evidence_for_complaint(client, cid, "before_hist.jpg", "INITIAL_REPORT")
    after_ev = upload_evidence_for_complaint(client, cid, "after_hist.jpg", "REPAIR_CLAIM")

    create_res = client.post(
        f"/api/complaints/{cid}/verifications",
        json={
            "before_evidence_id": before_ev["id"],
            "after_evidence_id": after_ev["id"]
        }
    )
    vid = create_res.json()["id"]

    # 1. Get by ID
    get_res = client.get(f"/api/complaints/{cid}/verifications/{vid}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == vid
    assert get_res.json()["complaint_id"] == cid

    # 2. List verifications
    list_res = client.get(f"/api/complaints/{cid}/verifications")
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert any(item["id"] == vid for item in items)

def test_verification_nonexistent_complaint(client):
    res = client.post("/api/complaints/nonexistent-uuid-12345/verifications", json={})
    assert res.status_code == 404
