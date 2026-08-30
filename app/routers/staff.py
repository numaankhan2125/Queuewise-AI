"""Counter Staff Workspace: live queue, Call Next / Start / Complete /
No-show actions, counter open-close.  ACL: staff see only their counter."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import require_staff
from ..database import get_db
from ..models import Counter, Token, User, utcnow
from ..services import token_engine
from ..services.notifications import notify
from ..services.ws import hub
from ..templates_env import templates

router = APIRouter()


def _staff_counter(db: Session, user: User) -> Counter:
    if not user.counter_id:
        raise HTTPException(400, "No counter assigned to your account")
    counter = db.get(Counter, user.counter_id)
    if counter is None:
        raise HTTPException(404, "Counter missing")
    return counter


def _workspace_ctx(db: Session, counter: Counter) -> dict:
    queue = token_engine.waiting_tokens(db, counter.id)
    current = (
        db.query(Token)
        .filter(Token.counter_id == counter.id,
                Token.status.in_(("called", "serving")))
        .order_by(Token.called_at.desc())
        .first()
    )
    recent = (
        db.query(Token)
        .filter(Token.counter_id == counter.id,
                Token.status.in_(("completed", "missed", "cancelled")))
        .order_by(Token.completed_at.desc().nullslast(),
                  Token.missed_at.desc().nullslast())
        .limit(8)
        .all()
    )
    return {
        "counter": counter,
        "queue": queue,
        "current": current,
        "recent": recent,
        "load": len(queue) + (1 if current else 0),
    }


@router.get("/workspace", response_class=HTMLResponse)
def workspace(request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_staff)):
    counter = _staff_counter(db, user)
    ctx = _workspace_ctx(db, counter)
    return templates.TemplateResponse(request, "staff_workspace.html", {
        "user": user, **ctx,
    })


def _counter_token(db: Session, token_id: int, user: User) -> Token:
    token = db.get(Token, token_id)
    if token is None:
        raise HTTPException(404, "Token not found")
    counter = _staff_counter(db, user)
    if token.counter_id != counter.id and user.role == "staff":
        raise HTTPException(403, "Token belongs to another counter")
    return token


@router.post("/workspace/call-next")
def call_next(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    counter = _staff_counter(db, user)
    token = token_engine.call_next(db, counter)
    if token is None:
        raise HTTPException(409, "Queue is empty")
    return RedirectResponse("/workspace", status_code=303)


@router.post("/tokens/{token_id}/start")
def start(token_id: int, db: Session = Depends(get_db),
          user: User = Depends(require_staff)):
    token_engine.start_service(db, _counter_token(db, token_id, user))
    return RedirectResponse("/workspace", status_code=303)


@router.post("/tokens/{token_id}/complete")
def complete(token_id: int, db: Session = Depends(get_db),
             user: User = Depends(require_staff)):
    token_engine.complete_service(db, _counter_token(db, token_id, user))
    return RedirectResponse("/workspace", status_code=303)


@router.post("/tokens/{token_id}/no-show")
def no_show(token_id: int, db: Session = Depends(get_db),
            user: User = Depends(require_staff)):
    """Staff-side immediate no-show (skips remaining grace)."""
    token = _counter_token(db, token_id, user)
    if token.status != "called":
        raise HTTPException(400, "Only called tokens can be marked missed")
    token.grace_expires_at = utcnow()
    db.commit()
    token_engine.expire_grace(db, token)
    return RedirectResponse("/workspace", status_code=303)


@router.post("/workspace/toggle-counter")
def toggle_counter(status: str = Form(...), db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
    counter = _staff_counter(db, user)
    if status not in ("open", "closed"):
        raise HTTPException(400, "Invalid status")
    was = counter.status
    counter.status = status
    db.commit()

    if was != status:
        verb = "opened" if status == "open" else "closed"
        notify(db, "supervisor",
               f"{counter.name} ({counter.location.name}) {verb} by staff "
               f"{user.name}.",
               extra={"event": "counter_status", "counter_id": counter.id})
        hub.publish([f"location:{counter.location_id}", "cqdcc"],
                    "counter_update",
                    {"counter_id": counter.id, "status": status})
    return RedirectResponse("/workspace", status_code=303)
