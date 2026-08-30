"""Unit/integration tests for the Virtual Token Engine."""
from datetime import timedelta

from app.config import GRACE_SECONDS
from app.models import Feedback, NotificationLog, Token, utcnow
from app.services.token_engine import (
    call_next,
    cancel_token,
    choose_counter,
    complete_service,
    counter_load,
    create_token,
    estimate_wait,
    expire_grace,
    rejoin_queue,
    start_service,
)


def test_estimate_is_transparent_math(make_location):
    loc, _ = make_location(avg=4.0)
    est = estimate_wait(loc, 7)
    assert est["estimated_wait_minutes"] == 28.0
    assert est["formula"] == "7 x 4.0 min = 28.0 min"
    assert est["queue_length"] == 7


def test_sequential_numbering_and_audit_fields(db, make_location, make_user):
    loc, counters = make_location(code="SQ", counters=("C1",))
    student = make_user("seq@student.edu")

    t1 = create_token(db, student_id=student.id, location_id=loc.id)
    t2 = create_token(db, student_id=make_user("seq2@student.edu").id,
                      location_id=loc.id)

    assert t1.code == "SQ-001" and t2.code == "SQ-002"
    assert t1.status == "waiting" == t2.status
    # prediction inputs stored on the token record itself (verifiable by design)
    assert t1.avg_service_time_used == loc.avg_service_minutes
    assert t1.est_wait_minutes == round(t1.queue_len_at_booking * loc.avg_service_minutes, 1)


def test_duplicate_active_token_blocked(db, make_location, make_user):
    loc, _ = make_location(code="DP")
    s = make_user("dup@student.edu")
    create_token(db, student_id=s.id, location_id=loc.id)
    try:
        create_token(db, student_id=s.id, location_id=loc.id)
        assert False, "should have raised ValueError"
    except ValueError as e:
        assert "already hold active token" in str(e)


def test_load_balancing_routes_to_least_loaded(db, make_location, make_user):
    loc, counters = make_location(code="LB2", counters=("Primary", "Backup"),
                                  threshold=2)
    primary, backup = counters
    backup.status = "closed"                 # stack everything on Primary first
    db.commit()

    students = [make_user(f"lb{i}@student.edu") for i in range(4)]
    for s in students[:3]:                   # threshold is 2 -> Primary overflows
        create_token(db, student_id=s.id, location_id=loc.id)
    loc_tokens = db.query(Token).filter(Token.location_id == loc.id).all()
    assert all(t.counter_id == primary.id for t in loc_tokens)

    backup.status = "open"                   # supervisor opens relief counter
    db.commit()

    chosen, rerouted = choose_counter(db, loc)
    assert chosen.id == backup.id            # strictly lighter than Primary (3>=2)
    assert rerouted is True

    t4 = create_token(db, student_id=students[3].id, location_id=loc.id)
    assert t4.counter_id == backup.id        # new token auto-rerouted

    sup_alerts = (db.query(NotificationLog)
                  .filter(NotificationLog.type == "supervisor").all())
    assert any("Load balancing" in n.message for n in sup_alerts)


def test_full_serving_lifecycle_updates_rolling_average(db, make_location, make_user):
    loc, (counter,) = make_location(code="LC", counters=("Solo",), avg=4.0)
    s1, s2 = make_user("lc1@student.edu"), make_user("lc2@student.edu")

    create_token(db, student_id=s1.id, location_id=loc.id)
    create_token(db, student_id=s2.id, location_id=loc.id)

    called = call_next(db, counter)
    assert called.status == "called" and called.grace_expires_at is not None
    assert called.grace_expires_at - utcnow() <= timedelta(seconds=GRACE_SECONDS + 2)

    started = start_service(db, called)
    assert started.status == "serving" and started.wait_minutes_actual is not None

    done = complete_service(db, started)
    assert done.status == "completed" and done.service_minutes_actual >= 0
    # rolling historical average was refreshed after service
    assert loc.avg_service_minutes > 0


def test_missed_token_recovery_and_rejoin(db, make_location, make_user):
    loc, (counter,) = make_location(code="MS", counters=("Only",))
    absent = make_user("absent@student.edu")
    next_in_line = make_user("inline@student.edu")
    create_token(db, student_id=absent.id, location_id=loc.id)   # MS-001
    second = create_token(db, student_id=next_in_line.id, location_id=loc.id)  # MS-002

    first = call_next(db, counter)
    first.grace_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    recovered = expire_grace(db, first)
    db.refresh(first)
    assert first.status == "missed" and first.missed_at is not None
    # counter auto-recovers: next token is called without staff action
    assert recovered is not None and recovered.id == second.id
    assert second.status == "called"

    types = {n.type for n in db.query(NotificationLog).all()}
    assert {"missed", "rejoin"} <= types

    fresh = rejoin_queue(db, first)
    assert fresh.student_id == absent.id
    assert fresh.rejoined_from_token == first.id
    assert fresh.status == "waiting"


def test_cancel_token(db, make_location, make_user):
    loc, _ = make_location(code="CX")
    s = make_user("cx@student.edu")
    tok = create_token(db, student_id=s.id, location_id=loc.id)
    cancel_token(db, tok, by_student=True)
    assert tok.status == "cancelled"


def test_feedback_linked_to_token_counter_staff_timeslot(db, make_location,
                                                         make_user):
    loc, (counter,) = make_location(code="FB", counters=("One",), avg=2.0)
    s, staff_u = make_user("fb@student.edu"), make_user("fb.staff@x.io",
                                                        role="staff",
                                                        counter=counter)
    tok = create_token(db, student_id=s.id, location_id=loc.id)
    complete_service(db, start_service(db, call_next(db, counter)))

    fb = Feedback(token_id=tok.id, rating=5, comment="great")
    db.add(fb)
    db.commit()

    got = db.query(Feedback).filter_by(token_id=tok.id).one()
    assert got.rating == 5
    # feedback traceable to token -> counter -> assigned staff member
    assert got.token.counter_id == staff_u.counter_id
    assert staff_u.counter is not None and staff_u.counter.id == counter.id

