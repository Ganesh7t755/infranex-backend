import io
import pytest

def test_public_complaints_list_and_privacy_boundaries(client):
    # 1. Create a complaint via standard endpoint
    create_payload = {
        "title": "Severe asphalt depression near bus stop",
        "category": "DAMAGED_ROAD",
        "description": "Bus stop pavement has sunk by 4 inches posing danger to pedestrians.",
        "location_address": "456 Market St, Downtown",
        "latitude": 37.7891,
        "longitude": -122.4014,
        "location_type": "GPS",
        "citizen_id": "private_citizen_123"
    }
    create_res = client.post("/api/complaints", json=create_payload)
    assert create_res.status_code == 201
    created_id = create_res.json()["id"]

    # 2. Query public complaints endpoint
    public_res = client.get("/api/public/complaints")
    assert public_res.status_code == 200
    public_list = public_res.json()
    assert len(public_list) >= 1

    item = next(c for c in public_list if c["id"] == created_id)
    assert item["title"] == "Severe asphalt depression near bus stop"
    assert item["category"] == "DAMAGED_ROAD"
    assert item["status"] == "SUBMITTED"
    assert item["latitude"] == 37.7891
    assert item["longitude"] == -122.4014
    
    # CRITICAL PRIVACY: citizen_id must NOT be exposed
    assert "citizen_id" not in item
    assert "description" not in item  # summary list omits full description

def test_public_complaint_filters_and_distance(client):
    # Create two complaints at different coordinates
    c1 = client.post("/api/complaints", json={
        "title": "Pothole at 1st and Main",
        "category": "POTHOLE",
        "description": "Deep tire-damaging hole in the slow lane.",
        "location_address": "100 Main St",
        "latitude": 37.7749,
        "longitude": -122.4194,
        "location_type": "GPS",
        "citizen_id": "citizen_a"
    }).json()

    c2 = client.post("/api/complaints", json={
        "title": "Overflowing public dumpster",
        "category": "GARBAGE",
        "description": "Debris scattered across sidewalk for 3 days.",
        "location_address": "800 Elm St",
        "latitude": 37.8044,
        "longitude": -122.2712,  # Oakland, ~13km away
        "location_type": "GPS",
        "citizen_id": "citizen_b"
    }).json()

    # Filter by category
    potholes = client.get("/api/public/complaints?category=POTHOLE").json()
    assert any(c["id"] == c1["id"] for c in potholes)
    assert not any(c["id"] == c2["id"] for c in potholes)

    # Filter by distance from San Francisco (37.7749, -122.4194) with 5km radius
    nearby = client.get("/api/public/complaints?lat=37.7749&lng=-122.4194&radius_km=5").json()
    assert any(c["id"] == c1["id"] for c in nearby)
    assert not any(c["id"] == c2["id"] for c in nearby)  # c2 is ~13km away

    # Test distance calculation response
    c1_nearby = next(c for c in nearby if c["id"] == c1["id"])
    assert c1_nearby["distance_km"] == 0.0

def test_public_complaint_missing_coordinates_graceful(client):
    # Create complaint with NO coordinates
    c = client.post("/api/complaints", json={
        "title": "Street lamp flickering on Oak Ave",
        "category": "BROKEN_STREETLIGHT",
        "description": "Flickering lamp creates dark spots at night.",
        "location_address": "Near 200 Oak Ave",
        "latitude": None,
        "longitude": None,
        "location_type": "MANUAL",
        "citizen_id": "citizen_c"
    }).json()

    # Discoverable in general public list
    public_list = client.get("/api/public/complaints").json()
    assert any(item["id"] == c["id"] for item in public_list)

    # Excluded when strict radius filtering is requested
    radius_list = client.get("/api/public/complaints?lat=37.7749&lng=-122.4194&radius_km=10").json()
    assert not any(item["id"] == c["id"] for item in radius_list)

def test_public_evidence_privacy_and_approval_controls(client):
    # Create complaint
    c = client.post("/api/complaints", json={
        "title": "Fallen powerline near playground",
        "category": "OTHER",
        "description": "Hazardous low-hanging wire needs emergency inspection.",
        "location_address": "Civic Park",
        "citizen_id": "citizen_priv"
    }).json()
    cid = c["id"]

    # Attach photo evidence (explicitly unapproved to test moderation workflow)
    file_bytes = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFdummyphotoevidence")
    upload_res = client.post(
        f"/api/complaints/{cid}/evidence",
        files={"file": ("evidence.jpg", file_bytes, "image/jpeg")},
        data={"evidence_type": "INITIAL_REPORT", "is_public_approved": "false"}
    )
    assert upload_res.status_code == 201
    assert upload_res.json()["is_public_approved"] is False
    eid = upload_res.json()["id"]

    # 1. Verify unapproved evidence is NOT in public complaint detail
    public_detail = client.get(f"/api/public/complaints/{cid}").json()
    assert len(public_detail["evidence_items"]) == 0
    assert "citizen_id" not in public_detail

    # 2. Verify accessing unapproved evidence file returns 403 Forbidden
    file_res = client.get(f"/api/public/complaints/{cid}/evidence/{eid}/file")
    assert file_res.status_code == 403
    assert "not been authorized" in file_res.json()["detail"]

    # 3. Explicitly approve evidence via reviewer moderation endpoint
    mod_res = client.patch(
        f"/api/complaints/{cid}/evidence/{eid}/moderation",
        json={"is_public_approved": True}
    )
    assert mod_res.status_code == 200
    assert mod_res.json()["is_public_approved"] is True

    # 4. Now evidence IS returned in public complaint detail
    public_detail_after = client.get(f"/api/public/complaints/{cid}").json()
    assert len(public_detail_after["evidence_items"]) == 1
    assert public_detail_after["evidence_items"][0]["id"] == eid

    # 5. Public evidence file download succeeds
    file_res_after = client.get(f"/api/public/complaints/{cid}/evidence/{eid}/file")
    assert file_res_after.status_code == 200
    assert file_res_after.headers["content-type"] == "image/jpeg"

    # 6. Verify default citizen upload is automatically public-approved for instant visibility
    upload_default = client.post(
        f"/api/complaints/{cid}/evidence",
        files={"file": ("default_civic.jpg", io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFdefaultcivic"), "image/jpeg")},
        data={"evidence_type": "INITIAL_REPORT"}
    )
    assert upload_default.status_code == 201
    assert upload_default.json()["is_public_approved"] is True
    default_eid = upload_default.json()["id"]

    public_detail_default = client.get(f"/api/public/complaints/{cid}").json()
    assert any(item["id"] == default_eid for item in public_detail_default["evidence_items"])

