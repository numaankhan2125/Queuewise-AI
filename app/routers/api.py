"""JSON REST API (used by the frontend JS and available for integrations)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_student, require_supervisor, get_current_user
from ..config import SERVICE_TYPES
from ..database import get_db, SessionLocal
from ..models import Counter, Location, Token, User
from ..services import analytics, token_engine

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/locations")
def locations(db: Session = Depends(get_db)):
    out = []
    for loc in db.query(Location).filter(Location.is_active.is_(True)).all():
        waiting = db.query(Token).filter(
            Token.location_id == loc.id, Token.status == "waiting").count()
        est = token_engine.estimate_wait(loc, waiting)
        out.append({
            "id": loc.id, "name": loc.name, "code": loc.code,
            "category": loc.category, "operating_hours": loc.operating_hours,
            "open_counters": db.query(Counter)
                .filter(Counter.location_id == loc.id,
                        Counter.status == "open").count(),
            **est,
        })
    return {"locations": out}


@router.get("/traffic")
def traffic(db: Session = Depends(get_db)):
    """Live congestion per service location — the decision-support feed."""
    return {"traffic": analytics.traffic_snapshot(db),
            "updated_at": datetime.utcnow().isoformat() + "Z"}


@router.get("/queues/live")
def live_queues(db: Session = Depends(get_db)):
    data = []
    for loc in db.query(Location).filter(Location.is_active.is_(True)).all():
        counters = db.query(Counter).filter(
            Counter.location_id == loc.id).order_by(Counter.id).all()
        now_serving = (
            db.query(Token)
            .filter(Token.location_id == loc.id,
                    Token.status.in_(("called", "serving")))
            .order_by(Token.called_at.desc().nullslast(), Token.number.desc())
            .first()
        )
        waiting = db.query(Token).filter(
            Token.location_id == loc.id, Token.status == "waiting").count()
        data.append({
            "location": loc.name, "location_id": loc.id,
            "now_serving": now_serving.code if now_serving else None,
            "waiting": waiting,
            "counters": [
                {"id": c.id, "name": c.name, "status": c.status}
                for c in counters
            ],
        })
    return {"queues": data}


class BookRequest(BaseModel):
    location_id: int
    service_type: str = "general"


@router.post("/tokens")
def api_book(body: BookRequest, db: Session = Depends(get_db),
             user: User = Depends(require_student)):
    if body.service_type not in SERVICE_TYPES:
        raise HTTPException(400, "Unknown service type")
    try:
        token = token_engine.create_token(
            db, student_id=user.id, location_id=body.location_id,
            service_type=body.service_type)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {
        "token": token_engine._dto(token),
        "position": token_engine.position_of(token, db),
    }


@router.get("/me/tokens")
def my_tokens_api(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    if user is None:
        raise HTTPException(401, "Login required")
    tokens = (
        db.query(Token)
        .filter(Token.student_id == user.id)
        .order_by(Token.issued_at.desc()).limit(50).all()
    )
    return {"tokens": [token_engine._dto(t) for t in tokens]}


@router.get("/cqdcc/kpis")
def cqdcc_kpis(db: Session = Depends(get_db),
               user: User = Depends(require_supervisor)):
    return analytics.kpis(db)


# expose for scheduler reuse in tests / scripts
session_factory = SessionLocal
