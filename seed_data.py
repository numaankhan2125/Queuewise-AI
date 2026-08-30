"""Seed the database with realistic campus data + one week of history.

Run:  python seed_data.py
Creates users/roles, locations, counters, ~a week of token history with
feedback, plus a few live tokens today so dashboards look real.
"""
import random
from datetime import datetime, timedelta

from app.database import SessionLocal, init_db
from app.models import (
    Base,
    Counter,
    Feedback,
    Location,
    NotificationLog,
    QueueSession,
    Token,
    User,
    hash_password,
)

random.seed(42)

LOCATIONS = [
    dict(name="Tuition Fee Counter", code="TF", category="Fee Payment",
         description="Semester tuition fee payment and receipts",
         operating_hours="09:30-16:30", avg=4.0, threshold=6,
         counters=["Tuition Counter 1", "Tuition Counter 2"]),
    dict(name="Bus Fee Counter", code="BF", category="Transport",
         description="Bus route fee payment and pass renewal",
         operating_hours="09:30-16:00", avg=3.5, threshold=4,
         counters=["Bus Fee Desk"]),
    dict(name="Examination Fee Counter", code="EF", category="Exam Cell",
         description="Exam registration and hall-ticket fee payment",
         operating_hours="09:30-16:30", avg=4.5, threshold=5,
         counters=["Exam Cell 1", "Exam Cell 2"]),
    dict(name="Central Cafeteria", code="CF", category="Cafeteria",
         description="Lunch and snack service",
         operating_hours="08:00-20:00", avg=2.5, threshold=8,
         counters=["Meal Counter A", "Meal Counter B"]),
    dict(name="Library Issue Desk", code="LB", category="Library",
         description="Book issue, return and clearance",
         operating_hours="09:00-18:00", avg=3.0, threshold=4,
         counters=["Issue Desk 1"]),
]

STAFF_MEMBERS = [
    ("Ravi Staff", "ravi.staff@queuewise.ai"),
    ("Sara Staff", "sara.staff@queuewise.ai"),
    ("Arun Staff", "arun.staff@queuewise.ai"),
    ("Divya Staff", "divya.staff@queuewise.ai"),
    ("Karthik Staff", "karthik.staff@queuewise.ai"),
]

STUDENTS = [
    ("Priya Sharma", "priya@student.edu", "22B81A0512"),
    ("Rahul Verma", "rahul@student.edu", "22B81A1205"),
    ("Aisha Khan", "aisha@student.edu", "23B81A0231"),
    ("Kiran Reddy", "kiran@student.edu", "21B81A0477"),
    ("Sneha Rao", "sneha@student.edu", "22B81A0566"),
    ("Arjun Das", "arjun@student.edu", "23B81A0918"),
    ("Meghana Iyer", "meghana@student.edu", "22B81A0733"),
    ("Zaid Ahmed", "zaid@student.edu", "21B81A1119"),
]


def make_users(db):
    def add(name, email, role, pw, counter=None, roll=None):
        u = User(name=name, email=email, role=role,
                 password_hash=hash_password(pw),
                 counter_id=counter.id if counter else None, roll_no=roll)
        db.add(u)
        return u

    add("Campus Administrator", "admin@queuewise.ai", "admin", "admin123")
    add("Meena Supervisor", "meena.sup@queuewise.ai", "supervisor", "super123")

    # one staff member on the first counter of each location
    for (name, email), counter in zip(STAFF_MEMBERS, db.query(Counter)
                                      .order_by(Counter.location_id,
                                                Counter.id).all()):
        add(name, email, "staff", "staff123", counter)

    students = [add(n, e, "student", "student123", roll=r)
                for n, e, r in STUDENTS]
    db.commit()
    return students


def make_locations_and_counters(db):
    for spec in LOCATIONS:
        loc = Location(
            name=spec["name"], code=spec["code"], category=spec["category"],
            description=spec["description"],
            operating_hours=spec["operating_hours"],
            avg_service_minutes=spec["avg"],
            overload_threshold=spec["threshold"])
        db.add(loc)
        db.flush()
        for cname in spec["counters"]:
            db.add(Counter(location_id=loc.id, name=cname))
    db.commit()


def history_day(db, day, students, locations_map, day_idx: int):
    """Create believable token history for `day` (a date). day_idx 0=most recent."""
    day_dt = datetime.combine(day, datetime.min.time())
    n_tokens = random.randint(38, 60)
    weights = [(10, 3), (11, 4), (12, 9), (13, 8), (14, 6),
               (15, 4), (16, 4), (17, 2)]
    hours = [h for h, w in weights for _ in range(w)]
    counters = db.query(Counter).all()

    for _ in range(n_tokens):
        counter = random.choice(counters)
        student = random.choice(students)
        hour = random.choice(hours)
        issued = day_dt + timedelta(hours=hour, minutes=random.randint(0, 59))
        if issued > datetime.utcnow():
            continue

        svc_base = counter.location.avg_service_minutes
        svc_actual = max(0.8, random.gauss(svc_base, svc_base * 0.25))
        wait_actual = random.uniform(0.5, 45)

        called = issued + timedelta(minutes=wait_actual)
        served = called + timedelta(minutes=random.uniform(0.2, 1.5))
        completed = served + timedelta(minutes=svc_actual)

        roll = random.random()
        if roll < 0.06:
            status, missed_at = "missed", called + timedelta(minutes=3)
            called_at, served_at, completed_at = called, None, None
            grace = called + timedelta(minutes=3)
        elif roll < 0.12:
            status = "cancelled"
            called_at = served_at = completed_at = missed_at = grace = None
        else:
            status = "completed"
            called_at, served_at, completed_at = called, served, completed
            missed_at, grace = None, None

        sess = (db.query(QueueSession)
                .filter_by(location_id=counter.location_id, session_date=day)
                .one_or_none())
        if not sess:
            sess = QueueSession(location_id=counter.location_id, session_date=day)
            db.add(sess)
            db.flush()
        sess.last_number += 1
        number = sess.last_number
        # globally unique code: include day index (D0..D6) to avoid collisions across seed days
        code = f"{counter.location.code}-D{day_idx}{number:03d}"

        waiting_at_booking = int(wait_actual / max(svc_base, .1))
        est_wait = round(waiting_at_booking * svc_base, 1)

        db.add(Token(
            code=code, number=number,
            location_id=counter.location_id, counter_id=counter.id,
            student_id=student.id,
            service_type=random.choice(["general", "fee", "document", "meal"]),
            status=status,
            queue_len_at_booking=waiting_at_booking,
            avg_service_time_used=svc_base,
            est_wait_minutes=est_wait,
            issued_at=issued, called_at=called_at,
            grace_expires_at=grace, served_at=served_at,
            completed_at=completed_at, missed_at=missed_at,
            wait_minutes_actual=round((called_at - issued).total_seconds() / 60, 1)
            if called_at else None,
            service_minutes_actual=round(svc_actual, 1) if served_at else None,
        ))

    db.commit()

    # CSAT on ~60% of that day's completed tokens
    completed = (db.query(Token)
                 .filter(Token.status == "completed",
                         Token.completed_at >= day_dt,
                         Token.completed_at < day_dt + timedelta(days=1))
                 .all())
    for t in completed:
        if random.random() < 0.6:
            rating = random.choices([5, 4, 3, 2], weights=[45, 35, 15, 5])[0]
            db.add(Feedback(
                token_id=t.id, rating=rating,
                comment=random.choice([
                    "", "", "Fast service, thank you!",
                    "Staff was helpful.", "Had to wait longer than expected.",
                    "Smooth experience overall.",
                ]),
                created_at=t.completed_at))
    db.commit()


def seed_today_live(db, students):
    """Leave a believable live state for demo: some waiting + one serving."""
    now = datetime.utcnow()
    tuition = db.query(Location).filter_by(code="TF").one()
    c1 = (db.query(Counter)
          .filter_by(location_id=tuition.id, name="Tuition Counter 1").one())

    sess = (db.query(QueueSession)
            .filter_by(location_id=tuition.id, session_date=now.date())
            .one_or_none()) or QueueSession(location_id=tuition.id)
    db.add(sess)
    db.flush()

    specs = [
        ("waiting", now - timedelta(minutes=25)),
        ("waiting", now - timedelta(minutes=19)),
        ("called", now - timedelta(minutes=6)),   # grace running -> demo no-show
        ("serving", now - timedelta(minutes=14)),
    ]
    for status, issued in specs:
        sess.last_number += 1
        t = Token(
            code=f"TF-{sess.last_number:03d}", number=sess.last_number,
            location_id=tuition.id, counter_id=c1.id,
            student_id=random.choice(students).id,
            service_type="fee", status=status,
            queue_len_at_booking=random.randint(2, 9),
            avg_service_time_used=tuition.avg_service_minutes,
            est_wait_minutes=round(random.randint(2, 9) * tuition.avg_service_minutes, 1),
            issued_at=issued)
        if status in ("called", "serving"):
            t.called_at = issued + timedelta(minutes=4)
        if status == "called":
            from app.config import GRACE_SECONDS
            t.grace_expires_at = (t.called_at or now) + timedelta(seconds=GRACE_SECONDS)
        if status == "serving":
            t.served_at = now - timedelta(minutes=2)
        db.add(t)
    db.commit()

    db.add(NotificationLog(type="booking",
                           message="Demo day seeded: live tokens active at Tuition Fee Counter."))
    db.commit()


def main():
    init_db()
    Base.metadata.drop_all(bind=__import__("app.database", fromlist=["engine"]).engine)
    init_db()

    db = SessionLocal()
    try:
        make_locations_and_counters(db)
        students = make_users(db)
        locations_map = {l.code: l for l in db.query(Location).all()}

        today = datetime.utcnow().date()
        for d in range(7, 0, -1):                     # last 7 days of history
            history_day(db, today - timedelta(days=d), students, locations_map, 8 - d)

        seed_today_live(db, students)

        counts = {
            "users": db.query(User).count(),
            "locations": db.query(Location).count(),
            "counters": db.query(Counter).count(),
            "tokens": db.query(Token).count(),
            "feedback": db.query(Feedback).count(),
        }
        print("Seed complete:", counts)
        print("Login -> admin@queuewise.ai/admin123 | priya@student.edu/student123 "
              "| ravi.staff@queuewise.ai/staff123 | meena.sup@queuewise.ai/super123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
