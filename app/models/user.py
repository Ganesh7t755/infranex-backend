import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum
from app.models.base import Base

class UserRole(str, enum.Enum):
    CITIZEN = "CITIZEN"
    REVIEWER = "REVIEWER"
    AUTHORITY = "AUTHORITY"
    ADMIN = "ADMIN"

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=True, index=True)
    full_name = Column(String(120), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.CITIZEN, index=True)
    department = Column(String(100), nullable=True)
    service_domains = Column(String(255), nullable=True, default="ROADS,ELECTRICITY,SANITATION,STREETLIGHTS,GENERAL_MAINTENANCE")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    def get_domains_list(self) -> list[str]:
        if not self.service_domains:
            return ["ROADS", "ELECTRICITY", "SANITATION", "STREETLIGHTS", "GENERAL_MAINTENANCE"]
        return [d.strip() for d in self.service_domains.split(",") if d.strip()]
