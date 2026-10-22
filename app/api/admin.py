from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.security import get_current_admin, AdminIdentity
from app.models.complaint import Complaint, ComplaintStatus, ComplaintCategory
from app.models.incident_assessment import IncidentAssessment
from app.models.review_decision import ReviewDecision
from app.models.authority_action import AuthorityAction
from app.models.dispute import ComplaintDispute
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.schemas.user import (
    UserResponse,
    UserCreateAdminRequest,
    UserUpdateAdminRequest,
    AuditLogResponse,
    SystemMetricsResponse,
)
from app.services.user_service import UserService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/api/admin", tags=["Administrator Operations"])

@router.get("/metrics", response_model=SystemMetricsResponse, summary="Executive platform KPI metrics")
def get_system_metrics(
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    total_complaints = db.query(Complaint).count()

    # Status breakdown
    status_counts = (
        db.query(Complaint.status, func.count(Complaint.id))
        .group_by(Complaint.status)
        .all()
    )
    status_dict = {
        (s.value if hasattr(s, 'value') else str(s)): cnt
        for s, cnt in status_counts
    }

    # Category breakdown
    cat_counts = (
        db.query(Complaint.category, func.count(Complaint.id))
        .group_by(Complaint.category)
        .all()
    )
    cat_dict = {
        (c.value if hasattr(c, 'value') else str(c)): cnt
        for c, cnt in cat_counts
    }

    # Domain breakdown
    domain_counts = (
        db.query(Complaint.service_domain, func.count(Complaint.id))
        .group_by(Complaint.service_domain)
        .all()
    )
    domain_dict = {
        (d or "UNASSIGNED"): cnt
        for d, cnt in domain_counts
    }

    # User metrics
    total_users = db.query(User).count()
    user_role_counts = (
        db.query(User.role, func.count(User.id))
        .group_by(User.role)
        .all()
    )
    user_role_dict = {
        (r.value if hasattr(r, 'value') else str(r)): cnt
        for r, cnt in user_role_counts
    }

    # Lifecycle metrics
    total_reviews = db.query(ReviewDecision).count()
    total_authority_actions = db.query(AuthorityAction).count()
    total_disputes = db.query(ComplaintDispute).count()

    # AI routing metrics
    ai_auto_routed = (
        db.query(IncidentAssessment)
        .filter(IncidentAssessment.review_required == False)
        .count()
    )
    ai_human_review = (
        db.query(IncidentAssessment)
        .filter(IncidentAssessment.review_required == True)
        .count()
    )
    total_ai_assessments = ai_auto_routed + ai_human_review
    auto_route_rate = round((ai_auto_routed / total_ai_assessments * 100), 2) if total_ai_assessments > 0 else 0.0

    return SystemMetricsResponse(
        total_complaints=total_complaints,
        status_breakdown=status_dict,
        category_breakdown=cat_dict,
        domain_breakdown=domain_dict,
        total_users=total_users,
        user_role_breakdown=user_role_dict,
        total_reviews=total_reviews,
        total_authority_actions=total_authority_actions,
        total_disputes=total_disputes,
        ai_auto_routed_count=ai_auto_routed,
        ai_human_review_count=ai_human_review,
        ai_auto_route_rate=auto_route_rate,
    )


@router.get("/users", response_model=List[UserResponse], summary="List and filter all registered platform users")
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    role: Optional[str] = Query(None, description="Filter by role (CITIZEN, REVIEWER, AUTHORITY, ADMIN)"),
    department: Optional[str] = Query(None, description="Filter by department name substring"),
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    users = service.list_users(skip=skip, limit=limit, role=role, department=department)
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value if hasattr(u.role, 'value') else str(u.role),
            department=u.department,
            service_domains=u.get_domains_list(),
            is_active=u.is_active,
            created_at=u.created_at,
            last_login_at=u.last_login_at
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, summary="Provision a new user or staff member")
def create_user(
    create_in: UserCreateAdminRequest,
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    new_user = service.create_user_admin(create_in)
    AuditService.log_event(
        db, action="ADMIN_CREATE_USER", user_id=admin.admin_id, username=admin.admin_id,
        role="ADMIN", resource_type="user", resource_id=new_user.id,
        details=f"Created user '{new_user.username}' with role '{new_user.role.value}'"
    )
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role.value if hasattr(new_user.role, 'value') else str(new_user.role),
        department=new_user.department,
        service_domains=new_user.get_domains_list(),
        is_active=new_user.is_active,
        created_at=new_user.created_at,
        last_login_at=new_user.last_login_at
    )


@router.patch("/users/{user_id}", response_model=UserResponse, summary="Modify user permissions, status, or role")
def update_user(
    user_id: str,
    update_in: UserUpdateAdminRequest,
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    service = UserService(db)
    updated_user = service.update_user_admin(user_id, update_in)
    AuditService.log_event(
        db, action="ADMIN_UPDATE_USER", user_id=admin.admin_id, username=admin.admin_id,
        role="ADMIN", resource_type="user", resource_id=updated_user.id,
        details=f"Updated user '{updated_user.username}' attributes"
    )
    return UserResponse(
        id=updated_user.id,
        username=updated_user.username,
        email=updated_user.email,
        full_name=updated_user.full_name,
        role=updated_user.role.value if hasattr(updated_user.role, 'value') else str(updated_user.role),
        department=updated_user.department,
        service_domains=updated_user.get_domains_list(),
        is_active=updated_user.is_active,
        created_at=updated_user.created_at,
        last_login_at=updated_user.last_login_at
    )


@router.get("/audit-logs", response_model=List[AuditLogResponse], summary="Query and filter system security audit trail")
def list_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: Optional[str] = Query(None, description="Filter by event action"),
    username: Optional[str] = Query(None, description="Filter by actor username"),
    role: Optional[str] = Query(None, description="Filter by actor role"),
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if username:
        query = query.filter(AuditLog.username == username.strip().lower())
    if role:
        query = query.filter(AuditLog.role == role.upper())

    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return logs


@router.get("/ai-performance", summary="AI Assessment and verification operational analytics")
def get_ai_performance(
    admin: AdminIdentity = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    assessments = db.query(IncidentAssessment).all()
    total = len(assessments)
    if total == 0:
        return {
            "total_assessments": 0,
            "average_confidence": 0.0,
            "category_match_rate": 0.0,
            "auto_route_rate": 0.0,
            "models_used": {},
        }

    conf_scores = [a.confidence_score for a in assessments if a.confidence_score is not None]
    avg_conf = round(sum(conf_scores) / len(conf_scores), 4) if conf_scores else 0.0
    matches = sum(1 for a in assessments if a.category_match is True)
    match_rate = round((matches / total * 100), 2)
    auto_routes = sum(1 for a in assessments if not a.review_required)
    auto_rate = round((auto_routes / total * 100), 2)

    models_dist: Dict[str, int] = {}
    for a in assessments:
        models_dist[a.model_name] = models_dist.get(a.model_name, 0) + 1

    return {
        "total_assessments": total,
        "average_confidence": avg_conf,
        "category_match_rate": match_rate,
        "auto_route_rate": auto_rate,
        "models_used": models_dist,
    }
