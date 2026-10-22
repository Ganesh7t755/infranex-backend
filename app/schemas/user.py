from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field, ConfigDict
from app.models.user import UserRole

class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    email: Optional[str] = Field(None, max_length=120)
    full_name: Optional[str] = Field(None, max_length=120)

class UserLoginRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=64)
    staff_id: Optional[str] = Field(None, min_length=2, max_length=64)
    password: Optional[str] = Field(None, max_length=128)
    requested_role: Optional[str] = Field(None)
    role: Optional[str] = Field(None)

    def get_effective_username(self) -> str:
        u = self.username or self.staff_id
        if not u:
            raise ValueError("username or staff_id is required")
        return u.strip()

    def get_effective_role(self) -> Optional[str]:
        return self.requested_role or self.role

class UserResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    department: Optional[str] = None
    service_domains: List[str] = []
    is_active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class UserCreateAdminRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    role: UserRole = Field(default=UserRole.CITIZEN)
    department: Optional[str] = None
    service_domains: Optional[List[str]] = None
    email: Optional[str] = None
    full_name: Optional[str] = None

class UserUpdateAdminRequest(BaseModel):
    role: Optional[UserRole] = None
    department: Optional[str] = None
    service_domains: Optional[List[str]] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None
    email: Optional[str] = None

class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SystemMetricsResponse(BaseModel):
    total_complaints: int
    status_breakdown: Dict[str, int]
    category_breakdown: Dict[str, int]
    domain_breakdown: Dict[str, int]
    total_users: int
    user_role_breakdown: Dict[str, int]
    total_reviews: int
    total_authority_actions: int
    total_disputes: int
    ai_auto_routed_count: int
    ai_human_review_count: int
    ai_auto_route_rate: float
