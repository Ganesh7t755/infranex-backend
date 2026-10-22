from datetime import datetime, timezone, timedelta
from typing import Optional, List
from dataclasses import dataclass, field
import jwt
from fastapi import Header, HTTPException, status
from app.core.config import settings

JWT_SECRET_KEY = getattr(settings, "JWT_SECRET_KEY", "infranex-cryptographic-jwt-secret-stage7-2026")
JWT_ALGORITHM = "HS256"


def create_access_token(user_id: str, role: str, department: Optional[str] = None, domains: Optional[List[str]] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": user_id,
        "role": role,
        "department": department or "Public Works",
        "domains": domains or ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=24)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@dataclass
class ReviewerIdentity:
    reviewer_id: str
    role: str = "REVIEWER"
    is_simulated: bool = True
    domains: List[str] = field(default_factory=lambda: ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])


@dataclass
class AuthorityIdentity:
    authority_id: str
    department: str = "Municipal Public Works"
    role: str = "AUTHORITY"
    is_simulated: bool = True
    domains: List[str] = field(default_factory=lambda: ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])


@dataclass
class AdminIdentity:
    admin_id: str
    role: str = "ADMIN"
    department: str = "Municipal IT & Systems Directorate"
    is_simulated: bool = False
    domains: List[str] = field(default_factory=lambda: ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])


@dataclass
class UserIdentity:
    user_id: str
    role: str
    department: Optional[str] = None
    domains: List[str] = field(default_factory=list)


def get_current_reviewer(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_reviewer_token: Optional[str] = Header(None, alias="X-Reviewer-Token"),
    x_reviewer_id: Optional[str] = Header(None, alias="X-Reviewer-ID"),
) -> ReviewerIdentity:
    """
    Enforces authorization boundary for reviewer endpoints with cryptographic JWT RBAC
    and backward-compatible simulation boundary for test suites.
    """
    # 1. Cryptographic JWT Bearer token authentication
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            token_role = payload.get("role", "")
            if token_role not in ("REVIEWER", "ADMIN"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Reviewer privileges required. Token role '{token_role}' is not authorized."
                )
            return ReviewerIdentity(
                reviewer_id=payload.get("sub", "authorized_reviewer"),
                role=token_role,
                is_simulated=False,
                domains=payload.get("domains", ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired reviewer token: {str(exc)}"
            )

    # 2. Reject header-based simulation in production
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Production reviewer operations are disabled until Stage 7 cryptographic JWT authentication and RBAC are deployed."
        )

    # 3. Development/test simulation boundary
    valid_token = getattr(settings, "DEV_REVIEWER_TOKEN", "infranex-dev-reviewer-secret-key-stage5")
    is_authorized = (x_role in ("REVIEWER", "ADMIN")) or (x_reviewer_token and x_reviewer_token == valid_token)
    
    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer authorization required. Please provide a valid Bearer token or development reviewer credentials."
        )

    reviewer_id = x_reviewer_id or "authorized_reviewer_sim"
    return ReviewerIdentity(reviewer_id=reviewer_id, role="REVIEWER", is_simulated=True)


def get_current_authority(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_authority_token: Optional[str] = Header(None, alias="X-Authority-Token"),
    x_authority_id: Optional[str] = Header(None, alias="X-Authority-ID"),
    x_department: Optional[str] = Header(None, alias="X-Department"),
    x_reviewer_token: Optional[str] = Header(None, alias="X-Reviewer-Token"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> AuthorityIdentity:
    """
    Enforces authorization boundary for municipal authority endpoints.
    Supports cryptographic JWT Bearer tokens and development simulation boundary.
    """
    # 1. Cryptographic JWT Bearer token authentication
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            token_role = payload.get("role", "")
            if token_role not in ("AUTHORITY", "ADMIN"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Authority privileges required. Token role '{token_role}' is not authorized."
                )
            return AuthorityIdentity(
                authority_id=payload.get("sub", "authorized_authority"),
                department=payload.get("department", "Unified Civic Infrastructure Directorate"),
                role=token_role,
                is_simulated=False,
                domains=payload.get("domains", ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired authority token: {str(exc)}"
            )

    # 2. Simulation checks
    clean_role = (x_role or "").strip()
    clean_auth_token = (x_authority_token or "").strip()
    clean_rev_token = (x_reviewer_token or "").strip()
    clean_user = (x_user_id or "").strip()

    # Anonymous access is denied
    if not clean_role and not clean_auth_token and not clean_rev_token and not clean_user and not (x_authority_id or "").strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required. Please provide valid authority credentials or Bearer token."
        )

    # Production safety guard
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Header-based authority operations are disabled in production until cryptographic JWT authentication is supplied."
        )

    # Reviewer credentials do not grant authority privileges
    if clean_role == "REVIEWER" or clean_rev_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer credentials do not grant authority privileges. Authority authorization required."
        )

    # Citizen cannot use authority endpoints
    if clean_user and not clean_auth_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Citizen identities do not have authority privileges. Authority authorization required."
        )

    # Validate authority token
    valid_token = getattr(settings, "DEV_AUTHORITY_TOKEN", "infranex-dev-authority-secret-key-stage3")
    is_authorized = bool(clean_auth_token) and clean_auth_token == valid_token

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authority authorization required. An unverified X-Role claim does not grant authority privileges; valid authority token required."
        )

    authority_id = (x_authority_id or "").strip() or "authorized_authority_sim"
    department = (x_department or "").strip() or "Municipal Public Works"
    return AuthorityIdentity(
        authority_id=authority_id,
        department=department,
        role="AUTHORITY",
        is_simulated=True,
        domains=["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"]
    )


def get_current_admin(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_role: Optional[str] = Header(None, alias="X-Role"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> AdminIdentity:
    """
    Enforces administrator authorization boundary.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            token_role = payload.get("role", "")
            if token_role != "ADMIN":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Administrator privileges required. Token role '{token_role}' is not authorized."
                )
            return AdminIdentity(
                admin_id=payload.get("sub", "admin"),
                role="ADMIN",
                department=payload.get("department", "Municipal IT & Systems Directorate"),
                is_simulated=False,
                domains=payload.get("domains", ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"])
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired admin token: {str(exc)}"
            )

    # Dev/test simulation boundary for admin
    if settings.ENVIRONMENT.lower() != "production":
        dev_admin_token = getattr(settings, "DEV_ADMIN_TOKEN", "infranex-dev-admin-secret-key-2026")
        if x_role == "ADMIN" or (x_admin_token and x_admin_token == dev_admin_token):
            return AdminIdentity(admin_id="admin_sim", role="ADMIN", is_simulated=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Administrator authorization required. Bearer token with ADMIN role is required."
    )


def get_current_citizen_id(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    x_citizen_id: Optional[str] = Header(None, alias="X-Citizen-ID"),
) -> str:
    """
    Resolves client citizen identity via Bearer token, X-User-ID, or X-Citizen-ID header.
    """
    if authorization and authorization.startswith("Bearer "):
        try:
            token = authorization.split(" ", 1)[1].strip()
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload.get("sub", x_user_id or "guest_citizen")
        except Exception:
            pass

    return x_citizen_id or x_user_id or "guest_citizen"


def get_current_user_optional(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
) -> UserIdentity:
    """
    Returns user identity if authenticated, otherwise returns guest.
    """
    if authorization and authorization.startswith("Bearer "):
        try:
            token = authorization.split(" ", 1)[1].strip()
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return UserIdentity(
                user_id=payload.get("sub", "unknown"),
                role=payload.get("role", "CITIZEN"),
                department=payload.get("department"),
                domains=payload.get("domains", [])
            )
        except Exception:
            pass

    return UserIdentity(
        user_id=x_user_id or "guest_citizen",
        role="CITIZEN",
        department="Civic Public",
        domains=[]
    )
