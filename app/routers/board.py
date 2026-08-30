"""Public NOW-SERVING display board + Campus Traffic Board (no login)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Counter, Location, Token
from ..services.analytics import traffic_snapshot
from ..services.token_engine import waiting_tokens
from ..templates_env import templates

router = APIRouter()


@router.get("/traffic", response_class=HTMLResponse)
def traffic_board(request: Request, db: Session = Depends(get_db),
                  user = Depends(get_current_user)):
    """Campus Traffic Board: live congestion at every service point."""
    return templates.TemplateResponse(request, "traffic.html", {
        "user": user,
        "traffic": traffic_snapshot(db),
        "updated_at": __import__("datetime").datetime.utcnow(),
    })


@router.get("/board", response_class=HTMLResponse)
def board_select(request: Request, db: Session = Depends(get_db)):
    locations = db.query(Location).filter(Location.is_active.is_(True)).all()
    return templates.TemplateResponse(request, "board_select.html", {
        "locations": locations,
    })


@router.get("/board/{location_id}", response_class=HTMLResponse)
def board(request: Request, location_id: int, db: Session = Depends(get_db)):
    loc = db.get(Location, location_id)
    counters = db.query(Counter).filter(
        Counter.location_id == location_id).order_by(Counter.id).all()

    rows = []
    for c in counters:
        current = (
            db.query(Token)
            .filter(Token.counter_id == c.id,
                    Token.status.in_(("called", "serving")))
            .order_by(Token.called_at.desc())
            .first()
        )
        queue = waiting_tokens(db, c.id)
        rows.append({
            "counter": c,
            "now_serving": current.code if current else "-",
            "state": current.status if current else "",
            "waiting": len(queue),
            "next_up": queue[0].code if queue else "-",
        })

    return templates.TemplateResponse(request, "board.html", {
        "location": loc, "rows": rows,
    })
