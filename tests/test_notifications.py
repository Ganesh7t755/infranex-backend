import pytest

def test_notification_creation_on_status_transition(client):
    # 1. Create a complaint belonging to citizen 'citizen_bob'
    c = client.post("/api/complaints", json={
        "title": "Damaged storm drain",
        "category": "OTHER",
        "description": "Drain grate is collapsed inwards.",
        "citizen_id": "citizen_bob"
    }).json()
    cid = c["id"]

    # Initially citizen_bob should have 0 notifications
    notifs_init = client.get("/api/notifications", headers={"X-User-ID": "citizen_bob"}).json()
    assert notifs_init["unread_count"] == 0
    assert len(notifs_init["items"]) == 0

    # 2. Transition status to UNDER_REVIEW
    trans_res = client.patch(f"/api/complaints/{cid}/status", json={
        "new_status": "UNDER_REVIEW",
        "actor_id": "reviewer_alice",
        "notes": "Assigning to regional drainage inspector"
    })
    assert trans_res.status_code == 200

    # 3. Check notifications for citizen_bob
    notifs_after = client.get("/api/notifications", headers={"X-User-ID": "citizen_bob"}).json()
    assert notifs_after["unread_count"] == 1
    assert len(notifs_after["items"]) == 1

    notif = notifs_after["items"][0]
    assert notif["complaint_id"] == cid
    assert notif["title"] == "Complaint Under Review"
    assert notif["is_read"] is False
    assert notif["notification_type"] == "STATUS_UPDATE"

def test_notification_read_and_mark_all_read(client):
    # Setup: create complaint and trigger two transitions
    c = client.post("/api/complaints", json={
        "title": "Broken pavement tiles",
        "category": "DAMAGED_ROAD",
        "description": "Pedestrians tripping over raised tiles.",
        "citizen_id": "citizen_claire"
    }).json()
    cid = c["id"]

    client.patch(f"/api/complaints/{cid}/status", json={"new_status": "UNDER_REVIEW"})
    client.patch(f"/api/complaints/{cid}/status", json={"new_status": "REPAIR_IN_PROGRESS"})

    notifs = client.get("/api/notifications", headers={"X-User-ID": "citizen_claire"}).json()
    assert notifs["unread_count"] == 2
    first_id = notifs["items"][0]["id"]

    # Mark first notification as read
    read_res = client.patch(f"/api/notifications/{first_id}/read", headers={"X-User-ID": "citizen_claire"})
    assert read_res.status_code == 200
    assert read_res.json()["is_read"] is True

    # Verify unread count is now 1
    notifs_mid = client.get("/api/notifications", headers={"X-User-ID": "citizen_claire"}).json()
    assert notifs_mid["unread_count"] == 1

    # Mark all read
    mark_all = client.post("/api/notifications/mark-all-read", headers={"X-User-ID": "citizen_claire"})
    assert mark_all.status_code == 200
    assert mark_all.json()["marked_read_count"] == 1

    # Verify unread count is now 0
    notifs_end = client.get("/api/notifications", headers={"X-User-ID": "citizen_claire"}).json()
    assert notifs_end["unread_count"] == 0

def test_notification_user_isolation(client):
    # Citizen X gets a notification
    cx = client.post("/api/complaints", json={
        "title": "Issue X",
        "category": "GARBAGE",
        "description": "Trash piles near school.",
        "citizen_id": "user_x"
    }).json()
    client.patch(f"/api/complaints/{cx['id']}/status", json={"new_status": "UNDER_REVIEW"})

    # User Y must not see User X's notifications
    y_notifs = client.get("/api/notifications", headers={"X-User-ID": "user_y"}).json()
    assert y_notifs["unread_count"] == 0
    assert len(y_notifs["items"]) == 0

    # User Y cannot mark User X's notification as read
    x_notifs = client.get("/api/notifications", headers={"X-User-ID": "user_x"}).json()
    x_nid = x_notifs["items"][0]["id"]

    unauth_read = client.patch(f"/api/notifications/{x_nid}/read", headers={"X-User-ID": "user_y"})
    assert unauth_read.status_code == 404

def test_notification_preferences_get_and_update(client):
    # Default preferences
    prefs = client.get("/api/notifications/preferences", headers={"X-User-ID": "pref_user"}).json()
    assert prefs["user_id"] == "pref_user"
    assert prefs["notify_status_updates"] is True
    assert prefs["notify_evidence_requests"] is True
    assert prefs["notify_resolution_alerts"] is True
    assert prefs["notify_nearby_alerts"] is True

    # Disable status updates
    update_res = client.put("/api/notifications/preferences", json={
        "notify_status_updates": False,
        "notify_nearby_alerts": False
    }, headers={"X-User-ID": "pref_user"})
    assert update_res.status_code == 200
    updated_prefs = update_res.json()
    assert updated_prefs["notify_status_updates"] is False
    assert updated_prefs["notify_nearby_alerts"] is False
    assert updated_prefs["notify_evidence_requests"] is True  # preserved

    # Verify that disabling status updates prevents new notifications from being created
    c = client.post("/api/complaints", json={
        "title": "Issue with muted alerts",
        "category": "POTHOLE",
        "description": "Deep hole on 5th avenue.",
        "citizen_id": "pref_user"
    }).json()
    client.patch(f"/api/complaints/{c['id']}/status", json={"new_status": "UNDER_REVIEW"})

    user_notifs = client.get("/api/notifications", headers={"X-User-ID": "pref_user"}).json()
    assert user_notifs["unread_count"] == 0
