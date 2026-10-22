import pytest
from app.models.user import User, UserRole
from app.core.security import create_access_token

class TestMultiRoleAuthenticationAndRegistration:
    def test_citizen_registration_and_login(self, client):
        # 1. Register a new citizen
        reg_payload = {
            "username": "sarah_citizen",
            "password": "SarahPassword2026!",
            "email": "sarah@example.com",
            "full_name": "Sarah Connor"
        }
        reg_res = client.post("/api/auth/register", json=reg_payload)
        assert reg_res.status_code == 201
        data = reg_res.json()
        assert "access_token" in data
        assert data["role"] == "CITIZEN"
        assert data["user_id"] == "sarah_citizen"

        # 2. Login with registered citizen credentials
        login_payload = {
            "username": "sarah_citizen",
            "password": "SarahPassword2026!",
            "role": "CITIZEN"
        }
        login_res = client.post("/api/auth/login", json=login_payload)
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        assert token is not None

        # 3. Verify session
        verify_res = client.get("/api/auth/verify", headers={"Authorization": f"Bearer {token}"})
        assert verify_res.status_code == 200
        assert verify_res.json()["valid"] is True
        assert verify_res.json()["role"] == "CITIZEN"

        # 4. Duplicate registration rejected
        dup_res = client.post("/api/auth/register", json=reg_payload)
        assert dup_res.status_code == 409

    def test_admin_login_success(self, client):
        # Admin authentication with default seed account
        login_payload = {
            "username": "admin",
            "password": "AdminPassword2026!",
            "role": "ADMIN"
        }
        res = client.post("/api/auth/login", json=login_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "ADMIN"
        assert data["user_id"] == "admin"
        assert "access_token" in data

    def test_get_current_user_profile(self, client):
        # Admin profile retrieval
        admin_token = create_access_token(user_id="admin", role="ADMIN", department="IT Directorate")
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "ADMIN"
        assert data["username"] == "admin"


class TestAdminOperationsAndRBAC:
    def test_admin_metrics_access_authorized(self, client):
        admin_token = create_access_token(user_id="admin", role="ADMIN")
        res = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
        assert res.status_code == 200
        data = res.json()
        assert "total_complaints" in data
        assert "status_breakdown" in data
        assert "category_breakdown" in data
        assert "domain_breakdown" in data
        assert "total_users" in data
        assert "ai_auto_route_rate" in data

    def test_admin_metrics_forbidden_for_citizen_and_reviewer(self, client):
        citizen_token = create_access_token(user_id="citizen_john", role="CITIZEN")
        res_cit = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {citizen_token}"})
        assert res_cit.status_code == 403

        reviewer_token = create_access_token(user_id="rev-001", role="REVIEWER")
        res_rev = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {reviewer_token}"})
        assert res_rev.status_code == 403

    def test_admin_user_provisioning_and_updating(self, client):
        admin_token = create_access_token(user_id="admin", role="ADMIN")
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Provision a new inspector staff
        new_staff_payload = {
            "username": "inspector_gadget",
            "password": "GadgetPassword2026!",
            "role": "AUTHORITY",
            "department": "BBMP Special Operations",
            "service_domains": ["ROADS", "GENERAL_MAINTENANCE"],
            "email": "gadget@bbmp.gov",
            "full_name": "Inspector Gadget"
        }
        create_res = client.post("/api/admin/users", json=new_staff_payload, headers=headers)
        assert create_res.status_code == 201
        created_user = create_res.json()
        assert created_user["username"] == "inspector_gadget"
        assert created_user["role"] == "AUTHORITY"
        user_id = created_user["id"]

        # 2. Update user attributes (deactivate and update department)
        update_payload = {
            "department": "BBMP Strategic Roads Unit",
            "is_active": False
        }
        patch_res = client.patch(f"/api/admin/users/{user_id}", json=update_payload, headers=headers)
        assert patch_res.status_code == 200
        updated = patch_res.json()
        assert updated["is_active"] is False
        assert updated["department"] == "BBMP Strategic Roads Unit"

        # 3. Deactivated user cannot log in
        login_res = client.post("/api/auth/login", json={
            "username": "inspector_gadget",
            "password": "GadgetPassword2026!"
        })
        assert login_res.status_code == 403

    def test_admin_audit_logs_and_ai_performance(self, client):
        # Trigger an action that creates an audit log
        login_res = client.post("/api/auth/login", json={
            "username": "admin",
            "password": "AdminPassword2026!",
            "role": "ADMIN"
        })
        assert login_res.status_code == 200
        admin_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Query audit logs
        audit_res = client.get("/api/admin/audit-logs", headers=headers)
        assert audit_res.status_code == 200
        logs = audit_res.json()
        assert isinstance(logs, list)
        assert len(logs) > 0

        # 2. Query AI performance metrics
        ai_res = client.get("/api/admin/ai-performance", headers=headers)
        assert ai_res.status_code == 200
        ai_data = ai_res.json()
        assert "total_assessments" in ai_data
        assert "average_confidence" in ai_data
        assert "auto_route_rate" in ai_data
