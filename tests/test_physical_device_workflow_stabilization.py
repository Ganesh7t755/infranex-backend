import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.complaint import ComplaintCategory, ComplaintStatus, LocationType

# Isolated in-memory database fixture
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="client")
def client_fixture():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_complaint_submission_with_zero_photos_routes_to_review_required(client: TestClient):
    """
    Issue A verification:
    Verify that citizen can submit a complaint with zero attached photos,
    it persists correctly, and routes to REVIEW_REQUIRED due to lack of photo evidence.
    """
    payload = {
        "title": "Deep Pothole on Main Road",
        "category": "POTHOLE",
        "description": "Hazardous pothole located near the junction with no street lighting.",
        "location_address": "Main Road Junction",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "location_type": "GPS",
        "citizen_id": "citizen_phone_user"
    }
    response = client.post("/api/complaints", json=payload)
    assert response.status_code == 201, f"Failed: {response.text}"
    data = response.json()
    assert data["id"] is not None
    assert data["reference_id"].startswith("INF-")
    assert data["title"] == "Deep Pothole on Main Road"
    # Initial creation status is SUBMITTED
    assert data["status"] == "SUBMITTED"

    # Verify Complaint listing (Issue B) retrieves this complaint
    list_resp = client.get("/api/complaints")
    assert list_resp.status_code == 200
    complaints = list_resp.json()
    assert len(complaints) == 1
    assert complaints[0]["id"] == data["id"]
    assert complaints[0]["status"] == "SUBMITTED"
    assert complaints[0]["evidence_count"] == 0


def test_staff_authentication_authority_valid_and_invalid(client: TestClient):
    """
    Issue C verification:
    Verify staff authentication for authority_officer requires valid credentials,
    rejects empty or wrong passwords, and returns valid role-scoped JWT.
    """
    # 1. Empty password must be rejected
    resp_empty = client.post("/api/auth/login", json={
        "username": "authority_officer",
        "password": "",
        "requested_role": "AUTHORITY"
    })
    assert resp_empty.status_code in (401, 422)

    # 2. Wrong password must be rejected
    resp_wrong = client.post("/api/auth/login", json={
        "username": "authority_officer",
        "password": "WrongPassword123!",
        "requested_role": "AUTHORITY"
    })
    assert resp_wrong.status_code == 401

    # 3. Valid mobile-friendly password must succeed
    resp_valid = client.post("/api/auth/login", json={
        "username": "authority_officer",
        "password": "Authority2026!",
        "requested_role": "AUTHORITY"
    })
    assert resp_valid.status_code == 200
    data = resp_valid.json()
    assert data["role"] == "AUTHORITY"
    assert "access_token" in data
    assert "ROADS" in data["service_domains"]

    # 4. Canonical password must also succeed
    resp_canon = client.post("/api/auth/login", json={
        "username": "authority_officer",
        "password": "AuthorityPassword2026!",
        "requested_role": "AUTHORITY"
    })
    assert resp_canon.status_code == 200
    assert resp_canon.json()["role"] == "AUTHORITY"


def test_staff_authentication_reviewer_and_role_isolation(client: TestClient):
    """
    Verify reviewer authentication succeeds with provisioned credentials,
    and privilege escalation / cross-role requests are blocked with 403.
    """
    # 1. Valid reviewer login
    resp_rev = client.post("/api/auth/login", json={
        "username": "reviewer_lead",
        "password": "Reviewer2026!",
        "requested_role": "REVIEWER"
    })
    assert resp_rev.status_code == 200
    rev_data = resp_rev.json()
    assert rev_data["role"] == "REVIEWER"

    # 2. Reviewer requesting AUTHORITY role must be rejected with 403
    resp_escalate = client.post("/api/auth/login", json={
        "username": "reviewer_lead",
        "password": "Reviewer2026!",
        "requested_role": "AUTHORITY"
    })
    assert resp_escalate.status_code == 403

    # 3. Unprovisioned account must be rejected with 401
    resp_unprov = client.post("/api/auth/login", json={
        "username": "fake_intruder",
        "password": "RandomPassword123!",
        "requested_role": "AUTHORITY"
    })
    assert resp_unprov.status_code == 401
