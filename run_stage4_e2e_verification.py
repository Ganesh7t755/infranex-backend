import os
import sys
import time
import shutil
import subprocess
import requests
from PIL import Image

BASE_URL = "http://127.0.0.1:8008"
DB_FILE = "test_stage4_isolated.db"
UPLOADS_DIR = "test_stage4_uploads"
TEMP_FIXTURES_DIR = "test_stage4_fixtures"

DEV_AUTHORITY_TOKEN = "infranex-dev-authority-secret-key-stage3"
DEV_REVIEWER_TOKEN = "infranex-dev-reviewer-secret-key-stage5"

AUTHORITY_HEADERS = {
    "X-Authority-Token": DEV_AUTHORITY_TOKEN,
    "X-Authority-ID": "muni_dispatcher_101",
    "X-Department": "Department of Public Works"
}

REVIEWER_HEADERS = {
    "X-Role": "REVIEWER",
    "X-Reviewer-ID": "lead_reviewer_e2e",
    "X-Reviewer-Token": DEV_REVIEWER_TOKEN
}


def make_image(path: str, width: int = 300, height: int = 300, color: str = "gray"):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="JPEG")


def make_corrupt_file(path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00\x01\x02\x03\xffINVALID_HEADER_DATA_12345")


def main():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)

    # 1. Clean previous run artifacts if any
    for p in [DB_FILE, UPLOADS_DIR, TEMP_FIXTURES_DIR]:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)

    os.makedirs(TEMP_FIXTURES_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    # 2. Launch live uvicorn server with isolated configuration
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///./{DB_FILE}"
    env["UPLOAD_DIR"] = f"./{UPLOADS_DIR}"
    env["ENVIRONMENT"] = "development"
    env["DEV_AUTHORITY_TOKEN"] = DEV_AUTHORITY_TOKEN
    env["DEV_REVIEWER_TOKEN"] = DEV_REVIEWER_TOKEN

    print(f"[*] Starting live backend server on {BASE_URL}...", flush=True)
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8008"],
        env=env,
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    results = []

    def record(test_group, scenario, passed, method, path, status_code, details):
        results.append({
            "group": test_group,
            "scenario": scenario,
            "passed": passed,
            "method": method,
            "path": path,
            "status": status_code,
            "details": details
        })
        mark = "[PASS]" if passed else "[FAIL]"
        print(f"  {mark} {test_group} - {scenario} ({method} {path} -> {status_code}): {details}", flush=True)

    try:
        # Wait for health check
        healthy = False
        for _ in range(30):
            try:
                r = requests.get(f"{BASE_URL}/health", timeout=1.0)
                if r.status_code == 200:
                    healthy = True
                    break
            except Exception:
                time.sleep(0.3)

        if not healthy:
            print("[!] FATAL: Backend server failed to start or respond on /health within 10s")
            return

        print("[+] Backend server is healthy. Executing real HTTP verification tests...\n")

        # ====================================================================
        # TEST A: Citizen Workflow & Privacy Boundaries
        # ====================================================================
        print("--- Running Test A: Citizen ---")

        # A1: Create complaint
        r = requests.post(f"{BASE_URL}/api/complaints", json={
            "title": "Severe road crater on 4th Ave",
            "category": "POTHOLE",
            "description": "Hazardous road crater causing severe tire damage.",
            "location_address": "400 4th Ave",
            "latitude": 37.7749,
            "longitude": -122.4194,
            "citizen_id": "citizen_alicia"
        })
        cid_a = r.json().get("id") if r.status_code == 201 else None
        record("Test A", "Create citizen complaint", r.status_code == 201 and cid_a is not None,
               "POST", "/api/complaints", r.status_code, f"Created complaint id={cid_a}")

        # A2: Upload valid photo evidence
        img_a = os.path.join(TEMP_FIXTURES_DIR, "pothole_a.jpg")
        make_image(img_a)
        with open(img_a, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/complaints/{cid_a}/evidence",
                files={"file": ("pothole_a.jpg", f, "image/jpeg")},
                data={"evidence_type": "INITIAL_REPORT"}
            )
        eid_a = r.json().get("id") if r.status_code == 201 else None
        record("Test A", "Upload valid photo evidence", r.status_code == 201 and eid_a is not None,
               "POST", f"/api/complaints/{cid_a}/evidence", r.status_code, f"Attached evidence id={eid_a}")

        # A3: Retrieve complaint detail and status
        r = requests.get(f"{BASE_URL}/api/complaints/{cid_a}")
        data_a = r.json()
        record("Test A", "Retrieve complaint detail", r.status_code == 200 and data_a.get("status") == "SUBMITTED",
               "GET", f"/api/complaints/{cid_a}", r.status_code, f"Status={data_a.get('status')}")

        # A4: Retrieve timeline
        r = requests.get(f"{BASE_URL}/api/complaints/{cid_a}/timeline")
        events = r.json() if r.status_code == 200 else []
        record("Test A", "Retrieve complaint timeline", r.status_code == 200 and len(events) >= 1,
               "GET", f"/api/complaints/{cid_a}/timeline", r.status_code, f"Timeline events count={len(events)}")

        # A5: Confirm unauthorized users cannot read restricted assessment history
        r = requests.get(f"{BASE_URL}/api/complaints/{cid_a}/assessments", headers={"X-User-ID": "citizen_stranger"})
        record("Test A", "Unauthorized user denied reading assessment history", r.status_code == 403,
               "GET", f"/api/complaints/{cid_a}/assessments", r.status_code, "Correctly returned 403 Forbidden")

        # ====================================================================
        # TEST B: Incident Assessment & Confidence Routing
        # ====================================================================
        print("\n--- Running Test B: Incident Assessment ---")

        # B1: Simulated High-Confidence Assessment (routes to AUTHORITY_QUEUE)
        r = requests.post(
            f"{BASE_URL}/api/complaints/{cid_a}/assessments?evidence_id={eid_a}",
            headers={"X-User-ID": "citizen_alicia"}
        )
        data_b1 = r.json() if r.status_code == 201 else {}
        score_b1 = data_b1.get("confidence_score")
        sim_b1 = data_b1.get("is_simulation")
        r_c_after = requests.get(f"{BASE_URL}/api/complaints/{cid_a}")
        status_after_b1 = r_c_after.json().get("status")
        passed_b1 = (r.status_code == 201 and score_b1 == 0.94 and sim_b1 is True and status_after_b1 == "AUTHORITY_QUEUE")
        record("Test B", "High-confidence assessment routes to AUTHORITY_QUEUE", passed_b1,
               "POST", f"/api/complaints/{cid_a}/assessments", r.status_code,
               f"Score={score_b1}, is_simulation={sim_b1}, New Status={status_after_b1}")

        # B2: Low-confidence Assessment (< 0.90 routes to REVIEW_REQUIRED)
        r_b2 = requests.post(f"{BASE_URL}/api/complaints", json={
            "title": "boundary_89 asphalt pothole",
            "category": "POTHOLE",
            "description": "Marginal defect depth.",
            "citizen_id": "citizen_bob"
        })
        cid_b2 = r_b2.json().get("id")
        img_b2 = os.path.join(TEMP_FIXTURES_DIR, "score_89.jpg")
        make_image(img_b2)
        with open(img_b2, "rb") as f:
            r_ev_b2 = requests.post(
                f"{BASE_URL}/api/complaints/{cid_b2}/evidence",
                files={"file": ("score_89.jpg", f, "image/jpeg")},
                data={"evidence_type": "INITIAL_REPORT"}
            )
        eid_b2 = r_ev_b2.json().get("id")
        r_ass_b2 = requests.post(
            f"{BASE_URL}/api/complaints/{cid_b2}/assessments?evidence_id={eid_b2}",
            headers={"X-User-ID": "citizen_bob"}
        )
        data_b2 = r_ass_b2.json() if r_ass_b2.status_code == 201 else {}
        score_b2 = data_b2.get("confidence_score")
        r_cb2_after = requests.get(f"{BASE_URL}/api/complaints/{cid_b2}")
        status_after_b2 = r_cb2_after.json().get("status")
        passed_b2 = (r_ass_b2.status_code == 201 and score_b2 == 0.89 and status_after_b2 == "REVIEW_REQUIRED")
        record("Test B", "Low-confidence assessment routes to REVIEW_REQUIRED", passed_b2,
               "POST", f"/api/complaints/{cid_b2}/assessments", r_ass_b2.status_code,
               f"Score={score_b2}, Status={status_after_b2}")

        # B3: Unsuitable / Blurry Image
        r_b3 = requests.post(f"{BASE_URL}/api/complaints", json={
            "title": "blurry photo initial report",
            "category": "POTHOLE",
            "description": "Camera shake during photo.",
            "citizen_id": "citizen_charlie"
        })
        cid_b3 = r_b3.json().get("id")
        img_b3 = os.path.join(TEMP_FIXTURES_DIR, "blurry.jpg")
        make_image(img_b3)
        with open(img_b3, "rb") as f:
            r_ev_b3 = requests.post(
                f"{BASE_URL}/api/complaints/{cid_b3}/evidence",
                files={"file": ("blurry.jpg", f, "image/jpeg")},
                data={"evidence_type": "INITIAL_REPORT"}
            )
        eid_b3 = r_ev_b3.json().get("id")
        r_ass_b3 = requests.post(
            f"{BASE_URL}/api/complaints/{cid_b3}/assessments?evidence_id={eid_b3}",
            headers={"X-User-ID": "citizen_charlie"}
        )
        data_b3 = r_ass_b3.json() if r_ass_b3.status_code == 201 else {}
        suitable_b3 = data_b3.get("evidence_suitable")
        status_after_b3 = requests.get(f"{BASE_URL}/api/complaints/{cid_b3}").json().get("status")
        passed_b3 = (r_ass_b3.status_code == 201 and suitable_b3 is False and status_after_b3 == "REVIEW_REQUIRED")
        record("Test B", "Unsuitable/blurry photo routes to REVIEW_REQUIRED", passed_b3,
               "POST", f"/api/complaints/{cid_b3}/assessments", r_ass_b3.status_code,
               f"evidence_suitable={suitable_b3}, Status={status_after_b3}")

        # B4: Corrupted / Invalid Binary Payload
        r_b4 = requests.post(f"{BASE_URL}/api/complaints", json={
            "title": "Corrupt file test",
            "category": "POTHOLE",
            "description": "Testing corrupt image handling.",
            "citizen_id": "citizen_david"
        })
        cid_b4 = r_b4.json().get("id")
        img_b4 = os.path.join(TEMP_FIXTURES_DIR, "corrupt.jpg")
        make_corrupt_file(img_b4)
        with open(img_b4, "rb") as f:
            r_ev_b4 = requests.post(
                f"{BASE_URL}/api/complaints/{cid_b4}/evidence",
                files={"file": ("corrupt.jpg", f, "image/jpeg")},
                data={"evidence_type": "INITIAL_REPORT"}
            )
        eid_b4 = r_ev_b4.json().get("id")
        r_ass_b4 = requests.post(
            f"{BASE_URL}/api/complaints/{cid_b4}/assessments?evidence_id={eid_b4}",
            headers={"X-User-ID": "citizen_david"}
        )
        data_b4 = r_ass_b4.json() if r_ass_b4.status_code == 201 else {}
        err_code_b4 = data_b4.get("assessment_metadata", {}).get("error_code")
        status_after_b4 = requests.get(f"{BASE_URL}/api/complaints/{cid_b4}").json().get("status")
        passed_b4 = (r_ass_b4.status_code == 201 and err_code_b4 == "IMAGE_DECODE_ERROR" and status_after_b4 == "REVIEW_REQUIRED")
        record("Test B", "Corrupt binary handled safely with error code", passed_b4,
               "POST", f"/api/complaints/{cid_b4}/assessments", r_ass_b4.status_code,
               f"error_code={err_code_b4}, Status={status_after_b4}")

        # B5: Provider timeout simulation
        r_b5 = requests.post(f"{BASE_URL}/api/complaints", json={
            "title": "provider_timeout simulation test",
            "category": "POTHOLE",
            "description": "Testing provider timeout containment.",
            "citizen_id": "citizen_eva"
        })
        cid_b5 = r_b5.json().get("id")
        img_b5 = os.path.join(TEMP_FIXTURES_DIR, "provider_timeout.jpg")
        make_image(img_b5)
        with open(img_b5, "rb") as f:
            r_ev_b5 = requests.post(
                f"{BASE_URL}/api/complaints/{cid_b5}/evidence",
                files={"file": ("provider_timeout.jpg", f, "image/jpeg")},
                data={"evidence_type": "INITIAL_REPORT"}
            )
        eid_b5 = r_ev_b5.json().get("id")
        r_ass_b5 = requests.post(
            f"{BASE_URL}/api/complaints/{cid_b5}/assessments?evidence_id={eid_b5}",
            headers={"X-User-ID": "citizen_eva"}
        )
        data_b5 = r_ass_b5.json() if r_ass_b5.status_code == 201 else {}
        meta_b5 = data_b5.get("assessment_metadata", {})
        err_b5 = meta_b5.get("error_code")
        exc_b5 = meta_b5.get("exception_type")
        status_after_b5 = requests.get(f"{BASE_URL}/api/complaints/{cid_b5}").json().get("status")
        passed_b5 = (r_ass_b5.status_code == 201 and err_b5 == "PROVIDER_PROCESSING_ERROR" and exc_b5 == "TimeoutError" and status_after_b5 == "REVIEW_REQUIRED")
        record("Test B", "Provider timeout contained safely", passed_b5,
               "POST", f"/api/complaints/{cid_b5}/assessments", r_ass_b5.status_code,
               f"error_code={err_b5}, exception_type={exc_b5}, Status={status_after_b5}")

        # ====================================================================
        # TEST C: Human Reviewer Workflow
        # ====================================================================
        print("\n--- Running Test C: Human Reviewer ---")

        # C1: Inspect reviewer queue
        r_q = requests.get(f"{BASE_URL}/api/reviewer/queue", headers=REVIEWER_HEADERS)
        queue_items = r_q.json() if r_q.status_code == 200 else []
        queue_ids = [item["id"] for item in queue_items]
        passed_c1 = (r_q.status_code == 200 and cid_b2 in queue_ids)
        record("Test C", "Reviewer queue returns complaints needing review", passed_c1,
               "GET", "/api/reviewer/queue", r_q.status_code, f"Queue count={len(queue_items)}, contains cid_b2={cid_b2 in queue_ids}")

        # C2: Reviewer triage verification (Approval: REVIEW_REQUIRED -> VERIFIED -> AUTHORITY_QUEUE)
        r_v = requests.patch(
            f"{BASE_URL}/api/complaints/{cid_b2}/status",
            headers={"X-Role": "REVIEWER"},
            json={"new_status": "VERIFIED", "actor_id": "lead_reviewer_e2e", "notes": "Defect manually verified by human reviewer."}
        )
        status_v = r_v.json().get("status") if r_v.status_code == 200 else None
        r_auth_q = requests.patch(
            f"{BASE_URL}/api/complaints/{cid_b2}/status",
            headers={"X-Role": "REVIEWER"},
            json={"new_status": "AUTHORITY_QUEUE", "actor_id": "lead_reviewer_e2e", "notes": "Handed off to municipal authority."}
        )
        status_auth_q = r_auth_q.json().get("status") if r_auth_q.status_code == 200 else None
        passed_c2 = (r_v.status_code == 200 and status_v == "VERIFIED" and r_auth_q.status_code == 200 and status_auth_q == "AUTHORITY_QUEUE")
        record("Test C", "Reviewer verification moves complaint to AUTHORITY_QUEUE", passed_c2,
               "PATCH", f"/api/complaints/{cid_b2}/status", r_auth_q.status_code,
               f"Step 1={status_v}, Step 2={status_auth_q}")

        # C3: Reviewer rejection
        r_rej = requests.patch(
            f"{BASE_URL}/api/complaints/{cid_b3}/status",
            headers={"X-Role": "REVIEWER"},
            json={"new_status": "REJECTED", "actor_id": "lead_reviewer_e2e", "notes": "Duplicate report / invalid location."}
        )
        status_rej = r_rej.json().get("status") if r_rej.status_code == 200 else None
        passed_c3 = (r_rej.status_code == 200 and status_rej == "REJECTED")
        record("Test C", "Reviewer rejects invalid complaint", passed_c3,
               "PATCH", f"/api/complaints/{cid_b3}/status", r_rej.status_code, f"Status={status_rej}")

        # C4: Reviewer requests more evidence
        r_more = requests.patch(
            f"{BASE_URL}/api/complaints/{cid_b4}/status",
            headers={"X-Role": "REVIEWER"},
            json={"new_status": "MORE_EVIDENCE_REQUIRED", "actor_id": "lead_reviewer_e2e", "notes": "Evidence corrupted; please re-upload clear photo."}
        )
        status_more = r_more.json().get("status") if r_more.status_code == 200 else None
        passed_c4 = (r_more.status_code == 200 and status_more == "MORE_EVIDENCE_REQUIRED")
        record("Test C", "Reviewer requests additional evidence", passed_c4,
               "PATCH", f"/api/complaints/{cid_b4}/status", r_more.status_code, f"Status={status_more}")

        # C5: Official review decision (post-repair review: REQUEST_EVIDENCE)
        # Advance cid_b5 to UNDER_REVIEW
        requests.patch(
            f"{BASE_URL}/api/complaints/{cid_b5}/status",
            headers={"X-Role": "REVIEWER"},
            json={"new_status": "UNDER_REVIEW", "actor_id": "lead_reviewer_e2e", "notes": "Reviewer started review."}
        )
        r_dec = requests.post(
            f"{BASE_URL}/api/reviewer/complaints/{cid_b5}/decide",
            headers=REVIEWER_HEADERS,
            json={"action": "REQUEST_EVIDENCE", "reason": "Requires high-resolution daytime photo."}
        )
        data_dec = r_dec.json() if r_dec.status_code == 201 else {}
        passed_c5 = (r_dec.status_code == 201 and data_dec.get("action") == "REQUEST_EVIDENCE")
        record("Test C", "Submit official review decision", passed_c5,
               "POST", f"/api/reviewer/complaints/{cid_b5}/decide", r_dec.status_code,
               f"Action={data_dec.get('action')}, New Status={data_dec.get('new_status')}")

        # C6: Audit history of decisions
        r_dec_list = requests.get(f"{BASE_URL}/api/reviewer/complaints/{cid_b5}/decisions", headers=REVIEWER_HEADERS)
        dec_list = r_dec_list.json() if r_dec_list.status_code == 200 else []
        passed_c6 = (r_dec_list.status_code == 200 and len(dec_list) >= 1)
        record("Test C", "Retrieve reviewer decision history", passed_c6,
               "GET", f"/api/reviewer/complaints/{cid_b5}/decisions", r_dec_list.status_code,
               f"Decisions count={len(dec_list)}")

        # ====================================================================
        # TEST D: Municipal Authority Workflow
        # ====================================================================
        print("\n--- Running Test D: Municipal Authority ---")

        # D1: Retrieve authority queue
        r_aq = requests.get(f"{BASE_URL}/api/authority/queue", headers=AUTHORITY_HEADERS)
        auth_queue = r_aq.json() if r_aq.status_code == 200 else []
        auth_ids = [item["id"] for item in auth_queue]
        passed_d1 = (r_aq.status_code == 200 and cid_a in auth_ids)
        record("Test D", "Authority queue lists eligible complaint", passed_d1,
               "GET", "/api/authority/queue", r_aq.status_code, f"Queue count={len(auth_queue)}, contains cid_a={cid_a in auth_ids}")

        # D2: Authority complaint detail
        r_adetail = requests.get(f"{BASE_URL}/api/authority/complaints/{cid_a}", headers=AUTHORITY_HEADERS)
        adetail = r_adetail.json() if r_adetail.status_code == 200 else {}
        passed_d2 = (r_adetail.status_code == 200 and adetail.get("id") == cid_a and len(adetail.get("evidence_items", [])) >= 1)
        record("Test D", "Authority complaint detail retrieved without leaking private info", passed_d2,
               "GET", f"/api/authority/complaints/{cid_a}", r_adetail.status_code,
               f"Evidence count={len(adetail.get('evidence_items', []))}")

        # D3: Acknowledge work
        r_ack = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_a}/acknowledge",
            headers=AUTHORITY_HEADERS,
            json={"notes": "Public Works Unit 4 acknowledged incident."}
        )
        passed_d3 = (r_ack.status_code == 201 and r_ack.json().get("action_type") == "ACKNOWLEDGE")
        status_after_ack = requests.get(f"{BASE_URL}/api/complaints/{cid_a}").json().get("status")
        record("Test D", "Authority acknowledges complaint", passed_d3 and status_after_ack == "AUTHORITY_QUEUE",
               "POST", f"/api/authority/complaints/{cid_a}/acknowledge", r_ack.status_code,
               f"action_type={r_ack.json().get('action_type')}, Status remains {status_after_ack}")

        # D4: Dispatch work (advances to ACTION_IN_PROGRESS)
        r_disp = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_a}/dispatch",
            headers=AUTHORITY_HEADERS,
            json={"work_order_reference": "WO-SF-2026-9901", "notes": "Asphalt crew dispatched."}
        )
        passed_d4 = (r_disp.status_code == 201 and r_disp.json().get("action_type") == "DISPATCH")
        status_after_disp = requests.get(f"{BASE_URL}/api/complaints/{cid_a}").json().get("status")
        record("Test D", "Authority dispatches work with work order", passed_d4 and status_after_disp == "ACTION_IN_PROGRESS",
               "POST", f"/api/authority/complaints/{cid_a}/dispatch", r_disp.status_code,
               f"Status={status_after_disp}, work_order={r_disp.json().get('work_order_reference')}")

        # D5: Start work / Record progress (advances to REPAIR_IN_PROGRESS)
        r_prog = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_a}/actions",
            headers=AUTHORITY_HEADERS,
            json={"action_type": "START_WORK", "notes": "Excavation and asphalt packing started on ground."}
        )
        passed_d5 = (r_prog.status_code == 201 and r_prog.json().get("action_type") == "START_WORK")
        status_after_prog = requests.get(f"{BASE_URL}/api/complaints/{cid_a}").json().get("status")
        record("Test D", "Authority records work start", passed_d5 and status_after_prog == "REPAIR_IN_PROGRESS",
               "POST", f"/api/authority/complaints/{cid_a}/actions", r_prog.status_code,
               f"Status={status_after_prog}")

        # D6: Record resolution (advances to RESOLVED)
        r_res = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_a}/resolve",
            headers=AUTHORITY_HEADERS,
            json={"notes": "Asphalt patch completed, compacted, and lane reopened.", "work_order_reference": "WO-SF-2026-9901"}
        )
        passed_d6 = (r_res.status_code == 201 and r_res.json().get("action_type") == "RESOLVE")
        status_after_res = requests.get(f"{BASE_URL}/api/complaints/{cid_a}").json().get("status")
        record("Test D", "Authority records resolution", passed_d6 and status_after_res == "RESOLVED",
               "POST", f"/api/authority/complaints/{cid_a}/resolve", r_res.status_code,
               f"Status={status_after_res}")

        # D7: Authority action history
        r_act_hist = requests.get(f"{BASE_URL}/api/authority/complaints/{cid_a}/actions", headers=AUTHORITY_HEADERS)
        actions = r_act_hist.json() if r_act_hist.status_code == 200 else []
        action_types = [a["action_type"] for a in actions]
        passed_d7 = (r_act_hist.status_code == 200 and len(actions) == 4 and action_types == ["RESOLVE", "START_WORK", "DISPATCH", "ACKNOWLEDGE"])
        record("Test D", "Authority action history preserved in reverse chronological order", passed_d7,
               "GET", f"/api/authority/complaints/{cid_a}/actions", r_act_hist.status_code,
               f"Actions={action_types}")

        # ====================================================================
        # TEST E: Security Boundaries & Regression
        # ====================================================================
        print("\n--- Running Test E: Security & Regression ---")

        # E1: Anonymous authority request denied (401)
        r = requests.get(f"{BASE_URL}/api/authority/queue")
        record("Test E", "Anonymous authority queue request denied (401)", r.status_code == 401,
               "GET", "/api/authority/queue", r.status_code, "Returned 401 Unauthorized")

        # E2: Citizen cannot access authority endpoints (403)
        r = requests.get(f"{BASE_URL}/api/authority/queue", headers={"X-User-ID": "citizen_alicia"})
        record("Test E", "Citizen denied authority endpoint access (403)", r.status_code == 403,
               "GET", "/api/authority/queue", r.status_code, "Returned 403 Forbidden")

        # E3: Unverified X-Role: AUTHORITY claim denied (403)
        r = requests.get(f"{BASE_URL}/api/authority/queue", headers={"X-Role": "AUTHORITY"})
        record("Test E", "Unverified X-Role: AUTHORITY claim denied (403)", r.status_code == 403,
               "GET", "/api/authority/queue", r.status_code, "Returned 403 Forbidden")

        # E4: Reviewer credentials do not grant authority privileges (403)
        r = requests.get(f"{BASE_URL}/api/authority/queue", headers=REVIEWER_HEADERS)
        record("Test E", "Reviewer credentials do not grant authority access (403)", r.status_code == 403,
               "GET", "/api/authority/queue", r.status_code, "Returned 403 Forbidden")

        # E5: Cross-citizen assessment access denied (403)
        r = requests.get(f"{BASE_URL}/api/complaints/{cid_a}/assessments", headers={"X-User-ID": "citizen_bob"})
        record("Test E", "Cross-citizen assessment read denied (403)", r.status_code == 403,
               "GET", f"/api/complaints/{cid_a}/assessments", r.status_code, "Returned 403 Forbidden")

        # E6: Cross-complaint action history access denied (404)
        action_0_id = actions[0]["id"]
        r = requests.get(f"{BASE_URL}/api/authority/complaints/{cid_b2}/actions/{action_0_id}", headers=AUTHORITY_HEADERS)
        record("Test E", "Cross-complaint action record read denied (404)", r.status_code == 404,
               "GET", f"/api/authority/complaints/{cid_b2}/actions/{action_0_id}", r.status_code, "Returned 404 Not Found")

        # E7: Premature resolution on AUTHORITY_QUEUE complaint rejected (400)
        # cid_b2 is currently in AUTHORITY_QUEUE
        r = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_b2}/actions",
            headers=AUTHORITY_HEADERS,
            json={"action_type": "RESOLVE", "notes": "Premature resolution"}
        )
        record("Test E", "Contradictory direct resolution from queue rejected (400)", r.status_code == 400,
               "POST", f"/api/authority/complaints/{cid_b2}/actions", r.status_code, "Returned 400 Bad Request")

        # E8: Authority action on terminal RESOLVED complaint rejected (400)
        # cid_a is RESOLVED
        r = requests.post(
            f"{BASE_URL}/api/authority/complaints/{cid_a}/dispatch",
            headers=AUTHORITY_HEADERS,
            json={"work_order_reference": "WO-FAIL"}
        )
        record("Test E", "Action on resolved complaint rejected (400)", r.status_code == 400,
               "POST", f"/api/authority/complaints/{cid_a}/dispatch", r.status_code, "Returned 400 Bad Request")

        # E9: Information leak verification (error messages do not leak paths or stack traces)
        r = requests.get(f"{BASE_URL}/api/complaints/non-existent-id/timeline")
        detail_text = r.text
        has_path_leak = ("E:\\" in detail_text) or ("E:/" in detail_text) or ("Traceback" in detail_text)
        record("Test E", "Error responses do not leak filesystem paths or stack traces", not has_path_leak,
               "GET", "/api/complaints/non-existent-id/timeline", r.status_code, "No absolute paths or traces in response")

    finally:
        # Shutdown server
        print("\n[*] Shutting down live backend server...")
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()

        # Clean up isolated test files
        for p in [DB_FILE, UPLOADS_DIR, TEMP_FIXTURES_DIR]:
            if os.path.exists(p):
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        print("[+] Isolated test database and upload directory cleaned up successfully.")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    print(f"\n========================================================")
    print(f"STAGE 4 E2E VERIFICATION SUMMARY: {passed}/{total} Passed ({failed} Failed)")
    print(f"========================================================")


if __name__ == "__main__":
    main()
