"""Student Portal: live queue visibility, remote token booking, my tokens,
feedback.  ACL: students can only act on their own tokens."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import require_student, require_user
from ..config import SERVICE_TYPES
from ..database import get_db
from ..models import Feedback, Location, Token, User
from ..services import analytics, token_engine
from ..services.notifications import notify
from ..services.ws import hub
from ..templates_env import templates

router = APIRouter()


def _location_cards(db: Session) -> list[dict]:
    """Portal cards now render from the same live traffic snapshot."""
    return analytics.traffic_snapshot(db)


@router.get("/portal", response_class=HTMLResponse)
def portal(request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_user)):
    active = (
        db.query(Token)
        .filter(Token.student_id == user.id,
                Token.status.in_(token_engine.ACTIVE_STATES))
        .all()
    )
    return templates.TemplateResponse(request, "student_portal.html", {
        "user": user, "cards": _location_cards(db),
        "service_types": SERVICE_TYPES,
        "active_tokens": [
            {"token": t, "position": token_engine.position_of(t, db)}
            for t in active
        ],
    })


@router.post("/portal/book")
def book(location_id: int = Form(...), service_type: str = Form("general"),
         db: Session = Depends(get_db), user: User = Depends(require_student)):
    try:
        token = token_engine.create_token(
            db, student_id=user.id, location_id=location_id,
            service_type=service_type)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse(f"/tokens/{token.id}", status_code=303)


@router.get("/my-tokens", response_class=HTMLResponse)
def my_tokens(request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_user)):
    tokens = (
        db.query(Token)
        .filter(Token.student_id == user.id)
        .order_by(Token.issued_at.desc())
        .limit(100)
        .all()
    )
    fb_token_ids = {f.token_id for f in db.query(Feedback).filter(
        Feedback.token.has(Token.student_id == user.id)).all()}
    return templates.TemplateResponse(request, "my_tokens.html", {
        "user": user, "tokens": tokens, "feedback_ids": fb_token_ids,
    })


def _own_token(db: Session, token_id: int, user: User) -> Token:
    token = db.get(Token, token_id)
    if token is None:
        raise HTTPException(404, "Token not found")
    if user.role == "student" and token.student_id != user.id:
        raise HTTPException(403, "You can only view your own tokens")
    return token


@router.get("/tokens/{token_id}", response_class=HTMLResponse)
def token_detail(token_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_user)):
    token = _own_token(db, token_id, user)
    feedback = db.query(Feedback).filter(Feedback.token_id == token.id).first()
    notifications = []
    if token.student_id == user.id:
        from ..models import NotificationLog
        notifications = (
            db.query(NotificationLog)
            .filter(NotificationLog.token_id == token.id)
            .order_by(NotificationLog.created_at.desc())
            .limit(10).all()
        )
    return templates.TemplateResponse(request, "token_detail.html", {
        "user": user, "token": token,
        "position": token_engine.position_of(token, db),
        "estimate": {
            "queue_length": token.queue_len_at_booking,
            "avg_service_time_min": token.avg_service_time_used,
            "estimated_wait_minutes": token.est_wait_minutes,
        },
        "feedback": feedback,
        "notifications": notifications,
    })


@router.post("/tokens/{token_id}/cancel")
def cancel(token_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_student)):
    token = _own_token(db, token_id, user)
    if token.student_id != user.id:
        raise HTTPException(403, "Not your token")
    token_engine.cancel_token(db, token, by_student=True)
    return RedirectResponse("/my-tokens", status_code=303)


@router.post("/tokens/{token_id}/rejoin")
def rejoin(token_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_student)):
    token = _own_token(db, token_id, user)
    if token.student_id != user.id:
        raise HTTPException(403, "Not your token")
    fresh = token_engine.rejoin_queue(db, token)
    return RedirectResponse(f"/tokens/{fresh.id}", status_code=303)


@router.post("/tokens/{token_id}/feedback")
def submit_feedback(token_id: int, rating: int = Form(...),
                    comment: str = Form(""),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_student)):
    token = _own_token(db, token_id, user)
    if token.student_id != user.id or token.status != "completed":
        raise HTTPException(400, "Feedback allowed only on completed tokens")
    if not 1 <= rating <= 5:
        raise HTTPException(400, "Rating must be 1-5")
    if db.query(Feedback).filter(Feedback.token_id == token.id).first():
        raise HTTPException(409, "Feedback already submitted")

    fb = Feedback(token_id=token.id, rating=rating, comment=comment.strip())
    db.add(fb)
    db.commit()

    notify(db, "feedback_received",
           f"CSAT {rating}/5 received for {token.code} "
           f"({token.counter.name}).",
           token_id=token.id, user_id=user.id,
           extra={"event": "feedback", "rating": rating})
    hub.publish(["cqdcc"], "feedback", {"rating": rating})

    return RedirectResponse(f"/tokens/{token.id}", status_code=303)
