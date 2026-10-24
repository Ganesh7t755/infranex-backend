import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.core.security_crypto import hash_password, verify_password
from app.core.config import settings
from app.schemas.user import UserCreateAdminRequest, UserUpdateAdminRequest

DEFAULT_SEED_USERS = [
    {
        "username": "admin",
        "password": "AdminPassword2026!",
        "role": UserRole.ADMIN,
        "department": "Municipal IT & Systems Directorate",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Chief System Administrator",
        "email": "admin@infranex.gov",
    },
    {
        "username": "authority_officer",
        "password": "AuthorityPassword2026!",
        "role": UserRole.AUTHORITY,
        "department": "Unified Civic Infrastructure Directorate",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Chief Municipal Field Engineer",
        "email": "authority.officer@infranex.gov",
    },
    {
        "username": "auth-001",
        "password": "AuthorityPassword2026!",
        "role": UserRole.AUTHORITY,
        "department": "Unified Civic Infrastructure Directorate",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Field Supervisor #001",
        "email": "auth001@infranex.gov",
    },
    {
        "username": "bbmp_roads",
        "password": "RoadsPassword2026!",
        "role": UserRole.AUTHORITY,
        "department": "BBMP - Road Infrastructure Division",
        "service_domains": "ROADS,GENERAL_MAINTENANCE",
        "full_name": "BBMP Road Ops Lead",
        "email": "roads@bbmp.gov",
    },
    {
        "username": "bescom_power",
        "password": "PowerPassword2026!",
        "role": UserRole.AUTHORITY,
        "department": "BESCOM - Power & Streetlight Operations",
        "service_domains": "ELECTRICITY,STREETLIGHTS",
        "full_name": "BESCOM Grid Dispatcher",
        "email": "power@bescom.gov",
    },
    {
        "username": "swm_sanitation",
        "password": "SanitationPassword2026!",
        "role": UserRole.AUTHORITY,
        "department": "SWM - Solid Waste Management",
        "service_domains": "SANITATION",
        "full_name": "SWM Logistics Officer",
        "email": "sanitation@swm.gov",
    },
    {
        "username": "reviewer_lead",
        "password": "ReviewerPassword2026!",
        "role": UserRole.REVIEWER,
        "department": "Civil Oversight Directorate",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Principal Human Reviewer",
        "email": "reviewer.lead@infranex.gov",
    },
    {
        "username": "rev-001",
        "password": "ReviewerPassword2026!",
        "role": UserRole.REVIEWER,
        "department": "AI Quality & Civic Review Team",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Review Specialist #001",
        "email": "rev001@infranex.gov",
    },
    {
        "username": "reviewer_1",
        "password": "ReviewerPassword2026!",
        "role": UserRole.REVIEWER,
        "department": "AI Quality & Civic Review Team",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "Review Specialist #1",
        "email": "reviewer1@infranex.gov",
    },
    {
        "username": "citizen_john",
        "password": "CitizenPassword2026!",
        "role": UserRole.CITIZEN,
        "department": "Civic Public",
        "service_domains": "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
        "full_name": "John Civic",
        "email": "john.citizen@infranex.org",
    },
]

class UserService:
    def __init__(self, db: Session):
        self.db = db

    def sync_default_seed_accounts(self) -> None:
        """Ensures all standard role accounts exist in the database with secure hashed credentials strictly in dev/test."""
        if not settings.is_development_or_test():
            return

        for seed in DEFAULT_SEED_USERS:
            existing = self.db.query(User).filter(User.username == seed["username"]).first()
            if not existing:
                new_user = User(
                    id=str(uuid.uuid4()),
                    username=seed["username"],
                    email=seed["email"],
                    full_name=seed["full_name"],
                    password_hash=hash_password(seed["password"]),
                    role=seed["role"],
                    department=seed["department"],
                    service_domains=seed["service_domains"],
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                self.db.add(new_user)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

    def authenticate_user(
        self,
        username: str,
        password: str,
        requested_role: Optional[str] = None
    ) -> User:
        clean_user = username.strip().lower()
        user = self.db.query(User).filter(User.username == clean_user).first()

        # If user not found in DB, check if it matches a default seed account strictly in development/test
        if not user and settings.is_development_or_test():
            seed = next((s for s in DEFAULT_SEED_USERS if s["username"].lower() == clean_user), None)
            if seed:
                user = User(
                    id=str(uuid.uuid4()),
                    username=seed["username"],
                    email=seed["email"],
                    full_name=seed["full_name"],
                    password_hash=hash_password(seed["password"]),
                    role=seed["role"],
                    department=seed["department"],
                    service_domains=seed["service_domains"],
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
                self.db.add(user)
                self.db.commit()
                self.db.refresh(user)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Account is not registered."
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated. Please contact an administrator."
            )

        # Check password against database hash or mobile/dev shortcut
        candidate_pass = password.strip()
        is_valid = verify_password(candidate_pass, user.password_hash)

        # Allow canonical dev shortcut passwords for convenience strictly in development/test
        if not is_valid and settings.is_development_or_test():
            if user.role == UserRole.AUTHORITY and candidate_pass in ("AuthorityPassword2026!", "Authority2026!"):
                is_valid = True
            elif user.role == UserRole.REVIEWER and candidate_pass in ("ReviewerPassword2026!", "Reviewer2026!"):
                is_valid = True
            elif user.role == UserRole.ADMIN and candidate_pass in ("AdminPassword2026!", "Admin2026!"):
                is_valid = True
            elif user.role == UserRole.CITIZEN and candidate_pass in ("CitizenPassword2026!", "Citizen2026!"):
                is_valid = True

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials."
            )

        # Prevent privilege escalation
        effective_role = user.role.value if hasattr(user.role, 'value') else str(user.role)
        if requested_role and requested_role.upper() != effective_role and effective_role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requested role '{requested_role}' conflicts with authorized role '{effective_role}'."
            )

        # Upgrade unhashed password to salted PBKDF2 hash
        if not user.password_hash.startswith("pbkdf2:"):
            user.password_hash = hash_password(candidate_pass)

        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(user)
        return user

    def register_citizen(
        self,
        username: str,
        password: str,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> User:
        clean_user = username.strip().lower()
        if len(clean_user) < 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username must be at least 3 characters long."
            )
        if len(password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long."
            )

        existing = self.db.query(User).filter(User.username == clean_user).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{clean_user}' is already registered."
            )

        if email:
            clean_email = email.strip().lower()
            existing_email = self.db.query(User).filter(User.email == clean_email).first()
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Email '{clean_email}' is already associated with another account."
                )
        else:
            clean_email = None

        new_user = User(
            id=str(uuid.uuid4()),
            username=clean_user,
            email=clean_email,
            full_name=full_name.strip() if full_name else None,
            password_hash=hash_password(password),
            role=UserRole.CITIZEN,
            department="Civic Public",
            service_domains="ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user

    def list_users(
        self,
        skip: int = 0,
        limit: int = 50,
        role: Optional[str] = None,
        department: Optional[str] = None,
    ) -> List[User]:
        query = self.db.query(User)
        if role:
            query = query.filter(User.role == role.upper())
        if department:
            query = query.filter(User.department.ilike(f"%{department}%"))
        return query.order_by(User.created_at.desc()).offset(skip).limit(limit).all()

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        return self.db.query(User).filter(User.username == username.strip().lower()).first()

    def create_user_admin(self, req: UserCreateAdminRequest) -> User:
        clean_user = req.username.strip().lower()
        existing = self.db.query(User).filter(User.username == clean_user).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{clean_user}' already exists."
            )

        domains_str = ",".join(req.service_domains) if req.service_domains else "ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE"
        new_user = User(
            id=str(uuid.uuid4()),
            username=clean_user,
            email=req.email.strip().lower() if req.email else None,
            full_name=req.full_name.strip() if req.full_name else None,
            password_hash=hash_password(req.password),
            role=req.role,
            department=req.department or "Municipal Operations",
            service_domains=domains_str,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user

    def update_user_admin(self, user_id: str, req: UserUpdateAdminRequest) -> User:
        user = self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if req.role is not None:
            user.role = req.role
        if req.department is not None:
            user.department = req.department
        if req.service_domains is not None:
            user.service_domains = ",".join(req.service_domains)
        if req.is_active is not None:
            user.is_active = req.is_active
        if req.full_name is not None:
            user.full_name = req.full_name
        if req.email is not None:
            user.email = req.email.strip().lower() if req.email else None

        self.db.commit()
        self.db.refresh(user)
        return user
