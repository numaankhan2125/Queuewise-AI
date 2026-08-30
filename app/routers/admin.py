"""Supervisor/Admin: Campus Queue Digital Command Center (CQ-DCC),
counter & location management, notification audit feed."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import require_admin, require_supervisor
from ..database import get_db
from ..models import Counter, Location, NotificationLog, Token, User
from ..services import analytics
from ..templates_env import templates

router = APIRouter()


@router.get("/cqdcc", response_class=HTMLResponse)
def cqdcc(request: Request, db: Session = Depends(get_db),
          user: User = Depends(require_supervisor)):
    return templates.TemplateResponse(request, "cqdcc.html", {
        "user": user,
        "kpis": analytics.kpis(db),
        "locations": db.query(Location).all(),
        "counters": db.query(Counter).all(),
        "recent_notifications": db.query(NotificationLog)
            .order_by(NotificationLog.created_at.desc()).limit(15).all(),
        "staff": db.query(User).filter(User.role == "staff").all(),
    })


@router.get("/admin/analytics-data")
def analytics_data(db: Session = Depends(get_db),
                   user: User = Depends(require_supervisor)):
    return {
        "volume_by_location": analytics.queue_volume_by_location(db),
        "peak_hours": analytics.peak_hours(db),
        "utilization": analytics.counter_utilization(db),
        "satisfaction": analytics.satisfaction_trend(db),
        "missed_rate": analytics.missed_rate_trend(db),
    }


@router.post("/admin/counters")
def manage_counter(location_id: int = Form(...), name: str = Form(...),
                   status: str = Form("open"), db: Session = Depends(get_db),
                   user: User = Depends(require_supervisor)):
    counter = Counter(location_id=location_id,
                      name=name.strip(), status=status)
    db.add(counter)
    db.commit()
    return RedirectResponse("/cqdcc", status_code=303)


@router.post("/admin/counters/{counter_id}/status")
def counter_status(counter_id: int, status: str = Form(...),
                   db: Session = Depends(get_db),
                   user: User = Depends(require_supervisor)):
    counter = db.get(Counter, counter_id)
    if counter and status in ("open", "closed"):
        counter.status = status
        db.commit()
    return RedirectResponse("/cqdcc", status_code=303)


@router.post("/admin/locations")
def add_location(name: str = Form(...), code: str = Form(...),
                 category: str = Form("general"),
                 avg_service_minutes: float = Form(4.0),
                 overload_threshold: int = Form(5),
                 operating_hours: str = Form("09:00-17:00"),
                 description: str = Form(""),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_admin)):
    loc = Location(
        name=name.strip(), code=code.strip().upper()[:6],
        category=category.strip(), description=description.strip(),
        avg_service_minutes=max(0.5, avg_service_minutes),
        overload_threshold=max(1, overload_threshold),
        operating_hours=operating_hours.strip(),
    )
    db.add(loc)
    db.commit()
    return RedirectResponse("/cqdcc", status_code=303)


@router.post("/admin/locations/{location_id}/toggle")
def toggle_location(location_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    loc = db.get(Location, location_id)
    if loc:
        loc.is_active = not loc.is_active
        db.commit()
    return RedirectResponse("/cqdcc", status_code=303)


@router.get("/admin/tokens", response_class=HTMLResponse)
def all_tokens(request: Request, status: str = "", db: Session = Depends(get_db),
               user: User = Depends(require_supervisor)):
    q = db.query(Token).order_by(Token.issued_at.desc())
    if status:
        q = q.filter(Token.status == status)
    return templates.TemplateResponse(request, "token_audit.html", {
        "user": user, "tokens": q.limit(200).all(), "status_filter": status,
    })
