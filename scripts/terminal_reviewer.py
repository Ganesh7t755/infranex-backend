#!/usr/bin/env python3
"""
InfraNex AI - Terminal Human Reviewer Console
----------------------------------------------
Enables municipal supervisors to review incoming civic complaints,
inspect uploaded defect images via clickable links / local paths,
evaluate offline AI assessments, approve/reject complaints, and
route approved reports directly to designated authority departments.
"""

import os
import sys
import time
from datetime import datetime, timezone

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure backend root is in python path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.core.database import SessionLocal
from app.models.complaint import Complaint, ComplaintStatus
from app.models.assignment import ComplaintAssignment
from app.models.status_event import ComplaintStatusEvent, ActorType
from app.schemas.complaint import ComplaintUpdateStatus
from app.services.complaint_service import ComplaintService

DOMAINS = {
    "1": ("ROADS", "BBMP - Road Infrastructure Division", "BBMP (Roads, Potholes, Cracks)"),
    "2": ("ELECTRICITY", "BESCOM - Power Infrastructure", "BESCOM (Streetlights, Wires, Transformer)"),
    "3": ("WATER_SUPPLY", "BWSSB - Water & Drainage Division", "BWSSB (Water Pipe Leak, Sewage)"),
    "4": ("SANITATION", "SWM - Solid Waste Management", "BBMP Solid Waste (Garbage, Trash, Litter)"),
}

def print_separator(char="=", length=72):
    print(char * length)

def review_complaint(complaint: Complaint, db) -> bool:
    """Interactively reviews a single complaint in the terminal."""
    print_separator("=")
    print(f" [!] HUMAN REVIEW REQUIRED: {complaint.reference_id or complaint.id[:8]}")
    print_separator("-")
    print(f" Title:       {complaint.title}")
    cat_val = complaint.category.value if hasattr(complaint.category, "value") else str(complaint.category)
    print(f" Category:    {cat_val}")
    print(f" Description: {complaint.description}")
    print(f" Location:    {complaint.location_address or 'No address provided'}")
    if complaint.latitude and complaint.longitude:
        print(f" GPS Coords:  Lat {complaint.latitude:.5f}, Lon {complaint.longitude:.5f}")
    print(f" Reported By: {complaint.citizen_id or 'Anonymous Citizen'}")
    print(f" Created At:  {complaint.created_at}")

    # Display Photographic Evidence
    print_separator("-")
    print(" [PHOTO EVIDENCE]:")
    if complaint.evidence_items:
        for idx, ev in enumerate(complaint.evidence_items, 1):
            http_url = f"http://localhost:8000/api/complaints/{complaint.id}/evidence/{ev.id}/file"
            local_path = ev.file_path if os.path.isabs(ev.file_path) else os.path.join(BACKEND_DIR, ev.file_path)
            local_uri = "file:///" + local_path.replace("\\", "/")
            print(f"   [{idx}] {ev.file_name} ({ev.mime_type})")
            print(f"       HTTP Link:   {http_url}")
            print(f"       Local File:  {local_uri}")
    else:
        print("   (No photo attached to this complaint)")

    # Display AI Assessment telemetry
    if complaint.assessments:
        latest_assessment = complaint.assessments[0]
        print_separator("-")
        print(" [OFFLINE AI ASSESSMENT]:")
        print(f"   Model:        {latest_assessment.model_name}")
        score_text = f"{latest_assessment.confidence_score:.1%}" if latest_assessment.confidence_score is not None else "N/A"
        print(f"   Confidence:   {score_text}")
        print(f"   Detected:     {latest_assessment.detected_category or 'Unclear / None'}")
        print(f"   Match Report: {'YES' if latest_assessment.category_match else 'MISMATCH'}")
        print(f"   Explanation:  {latest_assessment.explanation}")

    print_separator("=")

    # Interactive Human Decision
    while True:
        choice = input("\n>> Review Decision: [Y] Approve  |  [N] Reject  |  [S] Skip  |  [Q] Quit: ").strip().upper()
        if choice == "Q":
            return False
        elif choice == "S":
            print(">> Skipped for now.\n")
            return True
        elif choice == "N":
            reason = input("Enter rejection reason (or press Enter for default): ").strip()
            if not reason:
                reason = "Defect rejected upon human reviewer inspection."

            complaint_service = ComplaintService(db)
            complaint_service.transition_status(
                complaint_id=complaint.id,
                update_in=ComplaintUpdateStatus(
                    new_status=ComplaintStatus.REJECTED,
                    actor_id="terminal_human_reviewer",
                    notes=f"Human Reviewer rejected: {reason}"
                ),
                actor_type=ActorType.REVIEWER
            )
            print(f"[-] Complaint {complaint.reference_id} marked as REJECTED.\n")
            return True
        elif choice == "Y":
            # Prompt Domain Selection
            print("\nSelect Responsible Municipal Authority Domain:")
            for key, (domain_code, dept_name, display_label) in DOMAINS.items():
                print(f"  [{key}] {display_label}")

            # Guess default domain from category
            cat_str = str(complaint.category).upper()
            default_key = "1"
            if "STREETLIGHT" in cat_str or "POWER" in cat_str or "ELECTRIC" in cat_str:
                default_key = "2"
            elif "WATER" in cat_str or "PIPE" in cat_str or "DRAIN" in cat_str:
                default_key = "3"
            elif "GARBAGE" in cat_str or "WASTE" in cat_str:
                default_key = "4"

            domain_input = input(f"Choose domain [1-4] (Default: {default_key}): ").strip()
            if not domain_input or domain_input not in DOMAINS:
                domain_input = default_key

            chosen_domain, chosen_dept, chosen_label = DOMAINS[domain_input]
            notes = input("Enter optional reviewer notes (or press Enter): ").strip()
            if not notes:
                notes = f"Verified by human reviewer. Routed to {chosen_label}."

            complaint.service_domain = chosen_domain
            complaint.assigned_department = chosen_dept
            complaint.assignment_status = "ASSIGNED"

            # Record assignment audit
            assignment_entry = ComplaintAssignment(
                complaint_id=complaint.id,
                service_domain=chosen_domain,
                department=chosen_dept,
                assignment_status="ASSIGNED",
                assigned_by="terminal_human_reviewer",
                notes=notes,
                created_at=datetime.now(timezone.utc)
            )
            db.add(assignment_entry)

            # Transition to AUTHORITY_QUEUE
            complaint_service = ComplaintService(db)
            complaint_service.transition_status(
                complaint_id=complaint.id,
                update_in=ComplaintUpdateStatus(
                    new_status=ComplaintStatus.AUTHORITY_QUEUE,
                    actor_id="terminal_human_reviewer",
                    notes=notes
                ),
                actor_type=ActorType.REVIEWER
            )

            db.commit()
            print(f"[+] SUCCESS: Complaint {complaint.reference_id} dispatched to {chosen_dept} Authority Queue!\n")
            return True
        else:
            print("Invalid input. Please choose Y, N, S, or Q.")


def main():
    print_separator("=")
    print(" INFRANEX AI - TERMINAL HUMAN REVIEWER CONSOLE")
    print(" Live Triage & Municipal Department Dispatch Desk")
    print_separator("=")

    while True:
        db = SessionLocal()
        try:
            pending = (
                db.query(Complaint)
                .filter(Complaint.status == ComplaintStatus.REVIEW_REQUIRED)
                .order_by(Complaint.created_at.asc())
                .all()
            )

            if not pending:
                print("\n[i] Queue Clear! No complaints currently require human reviewer attention.")
                print("    (Incoming complaints with confidence <= 90% or unverified categories will appear here)")
                action = input("\nPress [Enter] to refresh, or [Q] to quit: ").strip().upper()
                if action == "Q":
                    print("Exiting reviewer console. Goodbye!")
                    break
                continue

            print(f"\n[*] Found {len(pending)} complaint(s) requiring human review:\n")
            continue_loop = True
            for complaint in pending:
                should_continue = review_complaint(complaint, db)
                if not should_continue:
                    continue_loop = False
                    break

            if not continue_loop:
                print("Exiting reviewer console. Goodbye!")
                break

        finally:
            db.close()


if __name__ == "__main__":
    main()
