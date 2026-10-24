import os
import importlib.util
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.core.config import Settings, INSECURE_DEV_JWT_SECRET
from app.core.security import create_access_token
from app.models.user import User
from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.review_decision import ReviewDecisionAction
from app.models.status_event import ActorType
from alembic.script import ScriptDirectory
from alembic.config import Config


# ---------------------------------------------------------------------------
# 1. Production Configuration & JWT Secret Validation Tests
# ---------------------------------------------------------------------------

def test_production_jwt_secret_validation_rejects_insecure_default(monkeypatch):
    """Production mode must reject default dev JWT secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", INSECURE_DEV_JWT_SECRET)
    
    with pytest.raises(ValueError, match="Insecure development default JWT_SECRET_KEY"):
        Settings()


def test_production_jwt_secret_validation_rejects_missing_or_blank(monkeypatch):
    """Production mode must reject empty or blank JWT secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "   ")
    
    with pytest.raises(ValueError, match="JWT_SECRET_KEY is missing or blank"):
        Settings()


def test_production_jwt_secret_validation_accepts_secure_key(monkeypatch):
    """Production mode succeeds when a strong, non-default secret key is configured."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-cryptographically-secure-key-2026-xyz-abc")
    
    s = Settings()
    assert s.is_production() is True
    assert s.is_development_or_test() is False


# ---------------------------------------------------------------------------
# 2. Production Authentication Rejects Hardcoded Fallback Credentials
# ---------------------------------------------------------------------------

def test_production_auth_rejects_hardcoded_fallback_credentials(client, db_session, monkeypatch):
    """In production, when user is not in database, in-memory VALID_STAFF_ACCOUNTS fallback is rejected with 401."""
    # Ensure database has no users so authentication must rely on fallback
    db_session.query(User).delete()
    db_session.commit()

    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.JWT_SECRET_KEY", "secure-prod-key-for-test-32bytes-long!")

    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "AdminPassword2026!",
        "requested_role": "ADMIN"
    })
    assert resp.status_code == 401
    assert "Invalid credentials" in resp.json().get("detail", "") or "Invalid username or password" in resp.json().get("detail", "")


def test_development_auth_allows_fallback_credentials(client, db_session, monkeypatch):
    """In development/test, in-memory fallback credentials work when database has no user."""
    db_session.query(User).delete()
    db_session.commit()

    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "development")

    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "AdminPassword2026!",
        "requested_role": "ADMIN"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "ADMIN"
    assert "access_token" in data


# ---------------------------------------------------------------------------
# 3. Development Identity Bypasses Rejected in Production
# ---------------------------------------------------------------------------

def test_reviewer_simulation_headers_rejected_in_production(client, monkeypatch):
    """X-Role / X-Reviewer-Token headers must fail with 403 in production."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.JWT_SECRET_KEY", "secure-prod-key-for-test-32bytes-long!")

    resp = client.get("/api/reviewer/queue", headers={
        "X-Role": "REVIEWER",
        "X-Reviewer-Token": "infranex-dev-reviewer-secret-key-stage5"
    })
    assert resp.status_code == 403
    assert "disabled in production" in resp.json()["detail"].lower()


def test_authority_simulation_headers_rejected_in_production(client, monkeypatch):
    """X-Authority-Token headers must fail with 403 in production."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.JWT_SECRET_KEY", "secure-prod-key-for-test-32bytes-long!")

    resp = client.get("/api/authority/queue", headers={
        "X-Role": "AUTHORITY",
        "X-Authority-Token": "infranex-dev-authority-secret-key-stage3"
    })
    assert resp.status_code == 403
    assert "disabled in production" in resp.json()["detail"].lower()


def test_admin_simulation_headers_rejected_in_production(client, monkeypatch):
    """X-Admin-Token headers must fail in production."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.JWT_SECRET_KEY", "secure-prod-key-for-test-32bytes-long!")

    resp = client.get("/api/admin/metrics", headers={
        "X-Role": "ADMIN",
        "X-Admin-Token": "infranex-dev-admin-secret-key-2026"
    })
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 4. Evidence Authorization Tests
# ---------------------------------------------------------------------------

def test_evidence_download_authorization(client, db_session, monkeypatch, tmp_path):
    """
    Validates evidence authorization rules:
    - Public approved evidence is accessible anonymously.
    - Private unapproved evidence is rejected for anonymous (401) and unassociated users (403).
    - Private evidence is accessible by the owner citizen, reviewer, admin, and assigned authority.
    """
    storage_file = tmp_path / "test_photo.jpg"
    storage_file.write_bytes(b"mock image content binary")
    monkeypatch.setattr("app.storage.file_storage.storage.resolve_path", lambda p: str(storage_file))

    # Seed a complaint with private evidence and public evidence
    complaint = Complaint(
        reference_id="INFRA-TEST-AUTH-01",
        title="Pothole on 5th Cross",
        category=ComplaintCategory.POTHOLE,
        description="Hazardous pothole",
        status=ComplaintStatus.SUBMITTED,
        location_type=LocationType.GPS,
        citizen_id="citizen_alice",
        service_domain="ROADS",
        assigned_department="BBMP - Road Infrastructure Division",
    )
    db_session.add(complaint)
    db_session.flush()

    private_ev = ComplaintEvidence(
        complaint_id=complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path="uploads/private.jpg",
        file_name="private.jpg",
        file_size=len(b"mock image content binary"),
        mime_type="image/jpeg",
        is_public_approved=False,
    )
    public_ev = ComplaintEvidence(
        complaint_id=complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path="uploads/public.jpg",
        file_name="public.jpg",
        file_size=len(b"mock image content binary"),
        mime_type="image/jpeg",
        is_public_approved=True,
    )
    db_session.add_all([private_ev, public_ev])
    db_session.commit()

    # 1. Public evidence: accessible without authentication
    resp_pub = client.get(f"/api/complaints/{complaint.id}/evidence/{public_ev.id}/file")
    assert resp_pub.status_code == 200
    assert resp_pub.content == b"mock image content binary"

    # 2. Private evidence: anonymous guest is rejected with 401
    resp_priv_anon = client.get(f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file")
    assert resp_priv_anon.status_code == 401

    # 3. Private evidence: unassociated citizen is rejected with 403
    bob_token = create_access_token(user_id="citizen_bob", role="CITIZEN")
    resp_priv_bob = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert resp_priv_bob.status_code == 403

    # 4. Private evidence: owner citizen is granted access (200)
    alice_token = create_access_token(user_id="citizen_alice", role="CITIZEN")
    resp_priv_owner = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert resp_priv_owner.status_code == 200

    # 5. Private evidence: Reviewer staff is granted access (200)
    rev_token = create_access_token(user_id="rev-001", role="REVIEWER")
    resp_priv_rev = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {rev_token}"}
    )
    assert resp_priv_rev.status_code == 200

    # 6. Private evidence: Admin staff is granted access (200)
    admin_token = create_access_token(user_id="admin-001", role="ADMIN")
    resp_priv_admin = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_priv_admin.status_code == 200

    # 7. Private evidence: Authority for the complaint's domain is granted access (200)
    auth_token = create_access_token(
        user_id="auth-roads",
        role="AUTHORITY",
        department="BBMP - Road Infrastructure Division",
        domains=["ROADS"]
    )
    resp_priv_auth = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert resp_priv_auth.status_code == 200

    # 8. Private evidence: Authority for a different domain is denied (403)
    power_token = create_access_token(
        user_id="auth-bescom",
        role="AUTHORITY",
        department="BESCOM - Power",
        domains=["ELECTRICITY"]
    )
    resp_priv_unauth = client.get(
        f"/api/complaints/{complaint.id}/evidence/{private_ev.id}/file",
        headers={"Authorization": f"Bearer {power_token}"}
    )
    assert resp_priv_unauth.status_code == 403


# ---------------------------------------------------------------------------
# 5. Production Startup Lifespan Safety
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_production_startup_does_not_create_all_or_seed():
    """In production, lifespan must not invoke Base.metadata.create_all or sync_default_seed_accounts."""
    from app.main import lifespan, app
    from app.core.config import settings

    with patch.object(settings, "ENVIRONMENT", "production"), \
         patch("app.main.Base.metadata.create_all") as mock_create_all, \
         patch("app.main.UserService") as mock_user_service:
        
        async with lifespan(app):
            pass

        mock_create_all.assert_not_called()
        mock_user_service.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Health Endpoint Exception Sanitization
# ---------------------------------------------------------------------------

def test_health_endpoint_sanitizes_errors_in_production(client, monkeypatch):
    """Health check in production returns generic error message without database traceback."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")

    with patch("sqlalchemy.orm.Session.execute", side_effect=RuntimeError("psycopg2.OperationalError: server closed connection")):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unhealthy: database connectivity failed"
        assert "psycopg2" not in data["database"]
        assert "OperationalError" not in data["database"]


def test_health_endpoint_shows_errors_in_dev(client, monkeypatch):
    """Health check in dev includes the error string for debugging."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "development")

    with patch("sqlalchemy.orm.Session.execute", side_effect=RuntimeError("dev sqlite connection failure")):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "unhealthy: dev sqlite connection failure" in data["database"]


# ---------------------------------------------------------------------------
# 7. Alembic Migration Order and Enum Reconciliation Tests
# ---------------------------------------------------------------------------

def test_alembic_migration_chain_and_enums():
    """Verifies that the new Alembic migration is correctly linked to head and covers all model enums."""
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    alembic_ini = os.path.join(backend_dir, "alembic.ini")
    
    config = Config(alembic_ini)
    script = ScriptDirectory.from_config(config)
    head_revision = script.get_current_head()
    
    assert head_revision == "h3789cdef013"

    rev = script.get_revision("h3789cdef013")
    assert rev.down_revision == "g2678cdef012"

    # Load migration module directly
    migration_file = os.path.join(backend_dir, "alembic", "versions", "h3789cdef013_reconcile_postgresql_enums.py")
    spec = importlib.util.spec_from_file_location("mig_h3789cdef013", migration_file)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    # Check ComplaintStatus
    for val in mig.COMPLAINT_STATUS_NEW_VALUES:
        assert val in [e.value for e in ComplaintStatus]

    # Check ActorType
    for val in mig.ACTOR_TYPE_NEW_VALUES:
        assert val in [e.value for e in ActorType]

    # Check ReviewDecisionAction
    for val in mig.REVIEW_DECISION_ACTION_NEW_VALUES:
        assert val in [e.value for e in ReviewDecisionAction]
