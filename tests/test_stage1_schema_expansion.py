import os
import subprocess
import sqlite3
import pytest
from datetime import datetime, timezone

from app.models.complaint import Complaint, ComplaintCategory, ComplaintStatus, LocationType
from app.models.evidence import ComplaintEvidence, EvidenceType
from app.models.status_event import ActorType
from app.models.incident_assessment import IncidentAssessment
from app.models.authority_action import AuthorityAction
from app.schemas.complaint import ComplaintUpdateStatus
from app.services.complaint_service import ComplaintService, VALID_TRANSITIONS

def test_incident_assessment_model_creation_and_fk(client, db_session):
    # 1. Create complaint and initial evidence
    complaint = Complaint(
        reference_id="INFRA-TEST-001",
        title="Deep Pothole at 5th St",
        category=ComplaintCategory.POTHOLE,
        description="Hazardous pothole in crosswalk",
        status=ComplaintStatus.SUBMITTED,
        location_type=LocationType.GPS,
    )
    db_session.add(complaint)
    db_session.flush()

    evidence = ComplaintEvidence(
        complaint_id=complaint.id,
        evidence_type=EvidenceType.INITIAL_REPORT,
        file_path="/uploads/test_pothole.jpg",
        file_name="test_pothole.jpg",
        file_size=204800,
        mime_type="image/jpeg",
        is_public_approved=False
    )
    db_session.add(evidence)
    db_session.flush()

    # 2. Attach IncidentAssessment with documented confidence score
    assessment = IncidentAssessment(
        complaint_id=complaint.id,
        evidence_id=evidence.id,
        provider_id="vision_test_provider",
        model_name="vision-classifier-v1",
        confidence_score=0.94,
        category_match=True,
        detected_category="POTHOLE",
        evidence_suitable=True,
        explanation="Confirmed severe asphalt depression matching POTHOLE category.",
        limitations="Shadow on south perimeter may obscure crack depth.",
        is_simulation=False,
        review_required=False,
        assessment_metadata={"laplacian_variance": 240.5, "bounding_box": [12, 34, 150, 180]}
    )
    db_session.add(assessment)
    db_session.commit()

    # 3. Verify associations and fields
    refreshed_complaint = db_session.query(Complaint).filter(Complaint.id == complaint.id).first()
    assert len(refreshed_complaint.assessments) == 1
    a = refreshed_complaint.assessments[0]
    assert a.confidence_score == 0.94
    assert a.category_match is True
    assert a.detected_category == "POTHOLE"
    assert a.evidence_suitable is True
    assert a.is_simulation is False
    assert a.review_required is False
    assert a.evidence.id == evidence.id
    assert a.complaint.id == complaint.id

def test_multiple_assessments_per_incident_preserve_history(client, db_session):
    # Multiple assessments allow retry / reassessment history preservation
    complaint = Complaint(
        reference_id="INFRA-TEST-002",
        title="Garbage accumulation on sidewalk",
        category=ComplaintCategory.GARBAGE,
        description="Piles of debris blocking pedestrians",
        status=ComplaintStatus.PROCESSING,
    )
    db_session.add(complaint)
    db_session.flush()

    # Assessment 1: Inconclusive initial scan
    a1 = IncidentAssessment(
        complaint_id=complaint.id,
        provider_id="provider_fast_check",
        model_name="suitability-v1",
        confidence_score=0.45,
        category_match=None,
        evidence_suitable=False,
        explanation="Image blurry and under-exposed.",
        limitations="Low light conditions",
        is_simulation=True,
        review_required=True,
        created_at=datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)
    )
    # Assessment 2: Higher resolution retry
    a2 = IncidentAssessment(
        complaint_id=complaint.id,
        provider_id="provider_deep_check",
        model_name="civic-multimodal-v2",
        confidence_score=0.92,
        category_match=True,
        detected_category="GARBAGE",
        evidence_suitable=True,
        explanation="Substantial municipal waste piles detected.",
        is_simulation=False,
        review_required=False,
        created_at=datetime(2026, 10, 18, 10, 2, 0, tzinfo=timezone.utc)
    )
    db_session.add_all([a1, a2])
    db_session.commit()

    refreshed = db_session.query(Complaint).filter(Complaint.id == complaint.id).first()
    assert len(refreshed.assessments) == 2
    # Ordered by created_at descending
    assert refreshed.assessments[0].confidence_score == 0.92
    assert refreshed.assessments[1].confidence_score == 0.45

def test_authority_action_model_and_association(client, db_session):
    complaint = Complaint(
        reference_id="INFRA-TEST-003",
        title="Damaged guardrail on overpass",
        category=ComplaintCategory.DAMAGED_ROAD,
        description="Bent steel barrier dangerous for vehicles",
        status=ComplaintStatus.AUTHORITY_QUEUE,
    )
    db_session.add(complaint)
    db_session.flush()

    action = AuthorityAction(
        complaint_id=complaint.id,
        authority_id="official_inspector_07",
        department="Department of Transportation - Barrier Maintenance",
        action_type="DISPATCH_CREW",
        work_order_reference="WO-2026-BR-004",
        notes="Crew dispatched with replacement W-beam section. Estimated completion 4 hours."
    )
    db_session.add(action)
    db_session.commit()

    refreshed = db_session.query(Complaint).filter(Complaint.id == complaint.id).first()
    assert len(refreshed.authority_actions) == 1
    act = refreshed.authority_actions[0]
    assert act.authority_id == "official_inspector_07"
    assert act.department == "Department of Transportation - Barrier Maintenance"
    assert act.action_type == "DISPATCH_CREW"
    assert act.work_order_reference == "WO-2026-BR-004"
    assert act.complaint.id == complaint.id

def test_new_status_transitions_valid_and_invalid(client, db_session):
    service = ComplaintService(db_session)
    complaint = Complaint(
        reference_id="INFRA-TEST-004",
        title="Broken Street Light at Elementary School",
        category=ComplaintCategory.BROKEN_STREETLIGHT,
        description="Fixture unlit causing dark pedestrian crosswalk",
        status=ComplaintStatus.SUBMITTED,
    )
    db_session.add(complaint)
    db_session.commit()

    # 1. Valid forward path: SUBMITTED -> PROCESSING
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.PROCESSING, notes="AI automated intake started")
    )
    assert c.status == ComplaintStatus.PROCESSING

    # 2. Valid high-confidence routing: PROCESSING -> AUTHORITY_QUEUE
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.AUTHORITY_QUEUE, notes="High-confidence AI assessment passed")
    )
    assert c.status == ComplaintStatus.AUTHORITY_QUEUE

    # 3. Valid authority dispatch: AUTHORITY_QUEUE -> ACTION_IN_PROGRESS
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.ACTION_IN_PROGRESS, notes="Maintenance crew assigned")
    )
    assert c.status == ComplaintStatus.ACTION_IN_PROGRESS

    # 4. Valid resolution: ACTION_IN_PROGRESS -> RESOLVED
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.RESOLVED, notes="Bulb and ballast replaced successfully")
    )
    assert c.status == ComplaintStatus.RESOLVED

    # 5. Invalid transition: RESOLVED directly to SUBMITTED must raise HTTP 400
    with pytest.raises(Exception) as exc_info:
        service.transition_status(
            complaint.id,
            ComplaintUpdateStatus(new_status=ComplaintStatus.SUBMITTED, notes="Invalid jump")
        )
    assert "Invalid state transition" in str(exc_info.value)

def test_human_review_workflow_transitions(client, db_session):
    service = ComplaintService(db_session)
    complaint = Complaint(
        reference_id="INFRA-TEST-005",
        title="Ambiguous roadway defect",
        category=ComplaintCategory.DAMAGED_ROAD,
        description="Needs inspection",
        status=ComplaintStatus.PROCESSING,
    )
    db_session.add(complaint)
    db_session.commit()

    # Low-confidence routing: PROCESSING -> REVIEW_REQUIRED
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.REVIEW_REQUIRED, notes="Confidence 0.68 requires human triage")
    )
    assert c.status == ComplaintStatus.REVIEW_REQUIRED

    # Reviewer requests more evidence: REVIEW_REQUIRED -> MORE_EVIDENCE_REQUIRED
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.MORE_EVIDENCE_REQUIRED, notes="Please provide closer angle")
    )
    assert c.status == ComplaintStatus.MORE_EVIDENCE_REQUIRED

    # Citizen provides photo, re-triggers: MORE_EVIDENCE_REQUIRED -> PROCESSING
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.PROCESSING, notes="Supplementary evidence uploaded")
    )
    assert c.status == ComplaintStatus.PROCESSING

    # Re-routed to review: PROCESSING -> REVIEW_REQUIRED
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.REVIEW_REQUIRED, notes="Second photo reviewed")
    )
    assert c.status == ComplaintStatus.REVIEW_REQUIRED

    # Human confirms defect: REVIEW_REQUIRED -> VERIFIED
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.VERIFIED, notes="Reviewer confirmed pothole severity")
    )
    assert c.status == ComplaintStatus.VERIFIED

    # Advances to authority queue: VERIFIED -> AUTHORITY_QUEUE
    c = service.transition_status(
        complaint.id,
        ComplaintUpdateStatus(new_status=ComplaintStatus.AUTHORITY_QUEUE, notes="Queued for dispatch")
    )
    assert c.status == ComplaintStatus.AUTHORITY_QUEUE

def test_existing_legacy_statuses_compatibility(client, db_session):
    service = ComplaintService(db_session)
    complaint = Complaint(
        reference_id="INFRA-TEST-006",
        title="Legacy flow pothole",
        category=ComplaintCategory.POTHOLE,
        description="Standard legacy flow test",
        status=ComplaintStatus.SUBMITTED,
    )
    db_session.add(complaint)
    db_session.commit()

    # Legacy transitions still work seamlessly:
    # SUBMITTED -> UNDER_REVIEW -> REPAIR_IN_PROGRESS -> REPAIR_CLAIMED -> VERIFICATION_PENDING -> RESOLVED_AFTER_REVIEW
    c = service.transition_status(complaint.id, ComplaintUpdateStatus(new_status=ComplaintStatus.UNDER_REVIEW))
    assert c.status == ComplaintStatus.UNDER_REVIEW

    c = service.transition_status(complaint.id, ComplaintUpdateStatus(new_status=ComplaintStatus.REPAIR_IN_PROGRESS))
    assert c.status == ComplaintStatus.REPAIR_IN_PROGRESS

    c = service.transition_status(complaint.id, ComplaintUpdateStatus(new_status=ComplaintStatus.REPAIR_CLAIMED))
    assert c.status == ComplaintStatus.REPAIR_CLAIMED

    c = service.transition_status(complaint.id, ComplaintUpdateStatus(new_status=ComplaintStatus.VERIFICATION_PENDING))
    assert c.status == ComplaintStatus.VERIFICATION_PENDING

    c = service.transition_status(complaint.id, ComplaintUpdateStatus(new_status=ComplaintStatus.RESOLVED_AFTER_REVIEW))
    assert c.status == ComplaintStatus.RESOLVED_AFTER_REVIEW

def test_isolated_migration_upgrade_and_downgrade(tmp_path):
    test_db = str(tmp_path / "test_migration_suite.db")
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{test_db}"

    # 1. Run migrations up to new head e0456abcd890
    cmd_up = ["alembic", "upgrade", "head"]
    res_up = subprocess.run(cmd_up, cwd="E:/InfraNex_AI/backend", env=env, capture_output=True, text=True)
    assert res_up.returncode == 0, f"Upgrade failed: {res_up.stderr}"

    # Verify tables created
    con = sqlite3.connect(test_db)
    cur = con.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "incident_assessments" in tables
    assert "authority_actions" in tables
    assert "complaints" in tables

    # Insert sample complaint and child records
    cur.execute("""
    INSERT INTO complaints (
        id, reference_id, title, category, description, status, location_type, created_at, updated_at
    ) VALUES ('test-c-1', 'INF-TEST-99', 'Pothole', 'POTHOLE', 'Crater', 'PROCESSING', 'GPS', datetime('now'), datetime('now'));
    """)
    cur.execute("""
    INSERT INTO incident_assessments (
        id, complaint_id, provider_id, model_name, confidence_score, evidence_suitable, explanation, is_simulation, review_required, assessment_metadata, created_at
    ) VALUES ('test-a-1', 'test-c-1', 'p_test', 'm_test', 0.95, 1, 'Valid', 0, 0, '{}', datetime('now'));
    """)
    cur.execute("""
    INSERT INTO authority_actions (
        id, complaint_id, authority_id, department, action_type, created_at
    ) VALUES ('test-act-1', 'test-c-1', 'officer_1', 'Roads', 'ACKNOWLEDGE', datetime('now'));
    """)
    con.commit()

    # 2. Downgrade to previous revision d9345fabd789
    con.close()
    cmd_down = ["alembic", "downgrade", "d9345fabd789"]
    res_down = subprocess.run(cmd_down, cwd="E:/InfraNex_AI/backend", env=env, capture_output=True, text=True)
    assert res_down.returncode == 0, f"Downgrade failed: {res_down.stderr}"

    con = sqlite3.connect(test_db)
    cur = con.cursor()
    tables_post_down = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    assert "incident_assessments" not in tables_post_down
    assert "authority_actions" not in tables_post_down
    # Core complaint is strictly preserved
    comp_count = cur.execute("SELECT count(*) FROM complaints;").fetchone()[0]
    assert comp_count == 1
    integrity = cur.execute("PRAGMA integrity_check;").fetchall()
    assert integrity == [('ok',)]
    con.close()
