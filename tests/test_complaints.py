import pytest
from app.models.complaint import ComplaintCategory, ComplaintStatus, LocationType

def test_create_complaint_success(client):
    payload = {
        "title": "Large pothole on Elm Street",
        "category": "POTHOLE",
        "description": "Deep pothole causing vehicle damage near the intersection of 5th Ave and Elm St.",
        "location_address": "Corner of 5th Ave and Elm St",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "location_type": "GPS",
        "citizen_id": "citizen_42"
    }
    response = client.post("/api/complaints", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["category"] == "POTHOLE"
    assert data["status"] == "SUBMITTED"
    assert data["reference_id"].startswith("INF-")
    assert data["latitude"] == pytest.approx(37.7749)
    assert data["longitude"] == pytest.approx(-122.4194)
    assert "id" in data
    assert "created_at" in data

    # Verify initial status event is created in timeline
    assert len(data["status_events"]) == 1
    assert data["status_events"][0]["new_status"] == "SUBMITTED"

def test_create_complaint_validation_failures(client):
    # Too short title
    response = client.post("/api/complaints", json={
        "title": "No",
        "category": "POTHOLE",
        "description": "Valid description of the issue"
    })
    assert response.status_code == 422

    # Invalid category
    response = client.post("/api/complaints", json={
        "title": "Broken bridge railing",
        "category": "FLYING_CARPET",
        "description": "Valid description of the issue"
    })
    assert response.status_code == 422

    # Too short description
    response = client.post("/api/complaints", json={
        "title": "Valid Title Here",
        "category": "POTHOLE",
        "description": "Bad"
    })
    assert response.status_code == 422

def test_list_complaints_with_filtering(client):
    # Create two complaints with different categories
    client.post("/api/complaints", json={
        "title": "Pothole in left lane",
        "category": "POTHOLE",
        "description": "Deep pothole damaging wheels."
    })
    client.post("/api/complaints", json={
        "title": "Illegal dumping in park",
        "category": "GARBAGE",
        "description": "Piles of trash left on park grass."
    })

    # List all
    all_res = client.get("/api/complaints")
    assert all_res.status_code == 200
    assert len(all_res.json()) == 2

    # Filter by category
    pothole_res = client.get("/api/complaints?category=POTHOLE")
    assert pothole_res.status_code == 200
    potholes = pothole_res.json()
    assert len(potholes) == 1
    assert potholes[0]["category"] == "POTHOLE"

    # Filter by non-existent category match
    streetlight_res = client.get("/api/complaints?category=BROKEN_STREETLIGHT")
    assert streetlight_res.status_code == 200
    assert len(streetlight_res.json()) == 0

def test_get_complaint_by_id_and_reference(client):
    created = client.post("/api/complaints", json={
        "title": "Streetlight flickering rapidly",
        "category": "BROKEN_STREETLIGHT",
        "description": "Light blinks non-stop creating hazard at night."
    }).json()

    complaint_id = created["id"]
    reference_id = created["reference_id"]

    # Fetch by UUID
    res_uuid = client.get(f"/api/complaints/{complaint_id}")
    assert res_uuid.status_code == 200
    assert res_uuid.json()["id"] == complaint_id

    # Fetch by Reference ID
    res_ref = client.get(f"/api/complaints/{reference_id}")
    assert res_ref.status_code == 200
    assert res_ref.json()["reference_id"] == reference_id

    # Fetch non-existent ID
    res_404 = client.get("/api/complaints/non-existent-id-12345")
    assert res_404.status_code == 404

def test_complaint_timeline(client):
    created = client.post("/api/complaints", json={
        "title": "Road subsidence after heavy rain",
        "category": "DAMAGED_ROAD",
        "description": "Asphalt has sunk several inches creating dangerous dip."
    }).json()

    timeline_res = client.get(f"/api/complaints/{created['id']}/timeline")
    assert timeline_res.status_code == 200
    events = timeline_res.json()
    assert len(events) == 1
    assert events[0]["new_status"] == "SUBMITTED"
    assert events[0]["previous_status"] is None

def test_status_transition_state_machine(client):
    created = client.post("/api/complaints", json={
        "title": "Dangerous road hole",
        "category": "DAMAGED_ROAD",
        "description": "Large hole in asphalt on highway shoulder."
    }).json()

    c_id = created["id"]

    # Invalid jump: SUBMITTED directly to RESOLVED_AFTER_REVIEW should fail (400)
    bad_transition = client.patch(f"/api/complaints/{c_id}/status", json={
        "new_status": "RESOLVED_AFTER_REVIEW",
        "notes": "Attempting illegal direct resolution"
    })
    assert bad_transition.status_code == 400
    assert "Invalid state transition" in bad_transition.json()["detail"]

    # Valid transition: SUBMITTED -> UNDER_REVIEW
    valid_step1 = client.patch(f"/api/complaints/{c_id}/status", json={
        "new_status": "UNDER_REVIEW",
        "actor_id": "reviewer_001",
        "notes": "Assigned to department inspector"
    })
    assert valid_step1.status_code == 200
    assert valid_step1.json()["status"] == "UNDER_REVIEW"

    # Valid step 2: UNDER_REVIEW -> REPAIR_IN_PROGRESS
    valid_step2 = client.patch(f"/api/complaints/{c_id}/status", json={
        "new_status": "REPAIR_IN_PROGRESS",
        "actor_id": "work_crew_leader",
        "notes": "Crew dispatched to site"
    })
    assert valid_step2.status_code == 200
    assert valid_step2.json()["status"] == "REPAIR_IN_PROGRESS"

    # Check updated timeline now has 3 events
    timeline = client.get(f"/api/complaints/{c_id}/timeline").json()
    assert len(timeline) == 3
    assert [e["new_status"] for e in timeline] == ["SUBMITTED", "UNDER_REVIEW", "REPAIR_IN_PROGRESS"]

def test_upload_and_retrieve_evidence(client):
    # Create complaint
    create_res = client.post("/api/complaints", json={
        "title": "Damaged asphalt surface",
        "category": "DAMAGED_ROAD",
        "description": "Cracked and buckling road surface near school entrance."
    })
    c_id = create_res.json()["id"]

    # Upload test image
    fake_image_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"\x00" * 100
    files = {"file": ("street_damage.jpg", fake_image_bytes, "image/jpeg")}
    upload_res = client.post(
        f"/api/complaints/{c_id}/evidence",
        files=files,
        data={"evidence_type": "INITIAL_REPORT"}
    )
    assert upload_res.status_code == 201
    evidence_data = upload_res.json()
    assert evidence_data["file_name"] == "street_damage.jpg"
    assert evidence_data["mime_type"] == "image/jpeg"
    assert evidence_data["file_size"] > 0
    assert "id" in evidence_data
    evidence_id = evidence_data["id"]

    # Retrieve complaint and verify evidence item is present
    detail = client.get(f"/api/complaints/{c_id}").json()
    assert len(detail["evidence_items"]) == 1
    assert detail["evidence_items"][0]["id"] == evidence_id

    # Retrieve evidence file content
    file_res = client.get(f"/api/complaints/{c_id}/evidence/{evidence_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "image/jpeg"
    assert file_res.content == fake_image_bytes

    # Timeline event was created for the evidence attachment
    timeline = client.get(f"/api/complaints/{c_id}/timeline").json()
    assert any("Evidence attached: street_damage.jpg" in e["notes"] for e in timeline)

def test_evidence_validation_rejects_unsupported_media_type(client):
    create_res = client.post("/api/complaints", json={
        "title": "Illegal dumping",
        "category": "GARBAGE",
        "description": "Construction debris piled on public sidewalk."
    })
    c_id = create_res.json()["id"]

    # Upload an invalid file type (.txt / text/plain)
    files = {"file": ("script.sh", b"#!/bin/bash\necho hello", "text/plain")}
    upload_res = client.post(
        f"/api/complaints/{c_id}/evidence",
        files=files,
        data={"evidence_type": "INITIAL_REPORT"}
    )
    assert upload_res.status_code == 415
    assert "Unsupported file type" in upload_res.json()["detail"]

def test_duplicate_submission_safeguard(client):
    payload = {
        "title": "Flickering streetlight outside library",
        "category": "BROKEN_STREETLIGHT",
        "description": "Streetlight flickers erratically after 8pm creating safety concern.",
        "citizen_id": "citizen_prevent_dup"
    }
    # First submission
    res1 = client.post("/api/complaints", json=payload)
    assert res1.status_code == 201
    ref1 = res1.json()["reference_id"]
    id1 = res1.json()["id"]

    # Immediate duplicate submission with identical content and citizen
    res2 = client.post("/api/complaints", json=payload)
    assert res2.status_code in (200, 201)
    ref2 = res2.json()["reference_id"]
    id2 = res2.json()["id"]

    # Must return the existing complaint rather than creating an unwanted duplicate
    assert ref1 == ref2
    assert id1 == id2


def test_delete_complaint(client):
    created = client.post("/api/complaints", json={
        "title": "Temporary hazard to delete",
        "category": "POTHOLE",
        "description": "Will be deleted immediately."
    }).json()
    c_id = created["id"]

    # Delete complaint
    del_res = client.delete(f"/api/complaints/{c_id}")
    assert del_res.status_code == 204

    # Verify 404 on subsequent get
    assert client.get(f"/api/complaints/{c_id}").status_code == 404

    # Also verify delete on non-existent complaint returns 404
    assert client.delete(f"/api/complaints/{c_id}").status_code == 404


