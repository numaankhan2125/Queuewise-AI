"""End-to-end API tests: auth/ACL, booking, staff flow, feedback, CQ-DCC."""
from app.models import Feedback, Token
from tests.conftest import login, logout


def _book(client_obj, location_id):
    r = client_obj.post("/api/tokens",
                        json={"location_id": location_id,
                              "service_type": "general"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_student_can_register_login_and_see_portal(client, make_location,
                                                   db, make_user):
    make_location(code="PT")
    r = client.post("/register", data={
        "name": "Portal Student", "email": "regme@student.edu",
        "roll_no": "22B81A9999", "password": "secret123"})
    assert r.status_code == 200 and r.url.path == "/portal"

    r = client.get("/portal")
    assert r.status_code == 200
    assert b"Live Campus Queues" in r.content


def test_booking_via_api_and_live_visibility(client, make_location, make_user):
    loc, _ = make_location(code="BK", counters=("K1",))
    make_user("portal@student.edu")
    login(client, "portal@student.edu")

    tok = _book(client, loc.id)
    assert tok["code"].startswith("BK-")
    assert tok["status"] == "waiting"

    live = client.get("/api/queues/live").json()["queues"]
    mine = next(q for q in live if q["location_id"] == loc.id)
    assert mine["waiting"] >= 1

    tokens = client.get("/api/me/tokens").json()["tokens"]
    assert any(t["id"] == tok["id"] for t in tokens)
    logout(client)


def test_duplicate_booking_conflict(client, make_location, db, make_user):
    loc, _ = make_location(code="CF2")
    make_user("dupportal@student.edu")
    login(client, "dupportal@student.edu")
    _book(client, loc.id)
    r = client.post("/api/tokens", json={"location_id": loc.id})
    assert r.status_code == 409
    logout(client)


def test_staff_full_flow_call_start_complete(client, make_location,
                                             db, make_user, ensure_user):
    loc, (counter,) = make_location(code="SF", counters=("Staffed",))
    staff = make_user("flow.staff@x.io", role="staff", counter=counter)

    ensure_user("portal@student.edu")
    login(client, "portal@student.edu")
    tok = _book(client, loc.id)
    logout(client)

    # second student books so queue has depth
    s2 = make_user("second@student.edu")
    t2 = Token(student_id=s2.id, location_id=loc.id, counter_id=counter.id,
               code="SF-002", number=2)
    db.add(t2)
    db.commit()

    login(client, staff.email)          # staff password pw123456 (fixture)
    r = client.get("/workspace")
    assert r.status_code == 200 and b"Call Next Token" in r.content

    r = client.post("/workspace/call-next")   # follows redirect -> workspace
    assert r.status_code == 200 and r.url.path == "/workspace"
    first = db.query(Token).filter_by(code=tok["code"]).one()
    assert first.status == "called"

    client.post(f"/tokens/{first.id}/start")
    db.refresh(first)
    assert first.status == "serving"

    client.post(f"/tokens/{first.id}/complete")
    db.refresh(first)
    assert first.status == "completed"
    assert first.service_minutes_actual is not None
    logout(client)


def test_feedback_and_csat_kpi(client, make_location, db, make_user,
                               ensure_user):
    loc, (counter,) = make_location(code="FB2", counters=("FBDesk",), avg=1.0)
    staff = make_user("fbk.staff@x.io", role="staff", counter=counter)
    ensure_user("portal@student.edu")
    login(client, "portal@student.edu")
    tok = _book(client, loc.id)
    logout(client)

    login(client, staff.email)
    client.post("/workspace/call-next")
    row = db.query(Token).filter_by(code=tok["code"]).one()
    client.post(f"/tokens/{row.id}/start")
    client.post(f"/tokens/{row.id}/complete")

    login(client, "portal@student.edu")
    r = client.post(f"/tokens/{row.id}/feedback",
                    data={"rating": "5", "comment": "superb"})
    assert r.status_code == 200 and r.url.path == f"/tokens/{row.id}"
    assert db.query(Feedback).filter_by(token_id=row.id).one().rating == 5
    logout(client)


def test_acl_students_cannot_touch_others_or_admin(client, make_location,
                                                   db, make_user):
    loc, (counter,) = make_location(code="AC", counters=("Solo",))
    owner = make_user("aclowner@student.edu")
    other = make_user("aclother@student.edu")

    tok = Token(student_id=owner.id, location_id=loc.id,
                counter_id=counter.id, code="AC-001", number=1)
    db.add(tok)
    db.commit()

    login(client, other.email)
    r = client.get(f"/tokens/{tok.id}")
    assert r.status_code == 403                      # ACL: not your token
    r = client.get("/cqdcc")
    assert r.status_code == 403                      # ACL: role gate
    r = client.post("/workspace/call-next")
    assert r.status_code == 403                      # ACL: staff-only action
    logout(client)


def test_supervisor_sees_cqdcc_and_analytics(client, db, make_user):
    sup = make_user("sup.view@x.io", role="supervisor")
    login(client, sup.email)
    assert client.get("/cqdcc").status_code == 200
    data = client.get("/admin/analytics-data").json()
    assert {"volume_by_location", "peak_hours",
            "utilization", "satisfaction", "missed_rate"} <= set(data)
    kpis = client.get("/api/cqdcc/kpis").json()
    assert "csat" in kpis and "waiting_now" in kpis
    logout(client)


def test_traffic_endpoint_levels_and_fields(client, make_location,
                                            make_user, db):
    loc, (c1, c2) = make_location(code="TR", counters=("T1", "T2"),
                                  avg=2.0, threshold=3)
    c2.status = "closed"                     # only c1 open -> capacity = 3
    db.commit()

    s = make_user("tr.student@x.io")
    for i in range(7):                        # 7 waiting vs capacity 3 -> packed
        db.add(Token(student_id=s.id if i == 0 else s.id + i + 1,
                     location_id=loc.id, counter_id=c1.id,
                     code=f"TR-{i+1:03d}", number=i + 1))
    db.commit()

    data = client.get("/api/traffic").json()["traffic"]
    row = next(t for t in data if t["location_id"] == loc.id)
    assert {"waiting", "load_pct", "traffic_key", "suggestion",
            "est_wait_minutes"} <= set(row)
    assert row["waiting"] == 7 and row["capacity"] == 3
    assert row["traffic_key"] == "packed"
    assert client.get("/traffic").status_code == 200   # public board renders


def test_public_board_accessible_without_login(client, make_location):
    loc, _ = make_location(code="BR")
    r = client.get(f"/board/{loc.id}")
    assert r.status_code == 200


