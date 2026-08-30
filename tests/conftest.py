"""Test bootstrap: isolated SQLite DB before any app import."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_TEST_DB = os.path.join(tempfile.gettempdir(), "queuewise_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["QUEUEWISE_DB"] = _TEST_DB

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Counter, Location, User, hash_password  # noqa: E402


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def make_location(db):
    def _make(code="TX", counters=("Desk A", "Desk B"), avg=4.0, threshold=5):
        loc = Location(name=f"Test Loc {code}", code=code, category="test",
                       avg_service_minutes=avg, overload_threshold=threshold)
        db.add(loc)
        db.flush()
        made = [Counter(location_id=loc.id, name=n) for n in counters]
        db.add_all(made)
        db.commit()
        return loc, made

    return _make


@pytest.fixture()
def make_user(db):
    def _make(email, role="student", counter=None):
        u = User(name=email.split("@")[0], email=email, role=role,
                 password_hash=hash_password("pw123456"),
                 counter_id=counter.id if counter else None)
        db.add(u)
        db.commit()
        return u

    return _make


@pytest.fixture()
def ensure_user(db):
    def _ensure(email, role="student"):
        u = db.query(User).filter_by(email=email).one_or_none()
        if u is None:
            u = User(name=email.split("@")[0], email=email, role=role,
                     password_hash=hash_password("pw123456"))
            db.add(u)
            db.commit()
        return u

    return _ensure


def login(client_obj, email):
    client_obj.post("/logout")
    r = client_obj.post("/login", data={"email": email, "password": "pw123456"})
    assert r.status_code in (200, 302)


def logout(client_obj):
    client_obj.post("/logout")
