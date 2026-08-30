"""Analytics service powering the CQ-DCC Command Center and reports."""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Counter, Feedback, Location, Token, utcnow


def estimate_wait(loc: Location, waiting: int) -> dict:
    """Imported lazily to avoid circulars; kept local for analytics use."""
    avg = float(loc.avg_service_minutes or 0)
    return {
        "queue_length": waiting,
        "avg_service_time_min": avg,
        "estimated_wait_minutes": round(waiting * avg, 1),
    }


def traffic_level(waiting: int, capacity: int) -> tuple[str, str, float]:
    """Congestion verdict from live queue vs counter capacity.

    Returns (label, css_key, load_pct).  capacity = open counters x threshold.
    """
    ratio = waiting / max(capacity, 1)
    pct = min(100.0, ratio * 100.0)
    if ratio < 0.4:
        return "Low", "low", pct
    if ratio < 0.8:
        return "Moderate", "moderate", pct
    if ratio < 1.2:
        return "High", "high", pct
    return "Very High", "packed", pct


def traffic_snapshot(db: Session) -> list[dict]:
    """Per-location live traffic for the Traffic Board and portal cards."""
    snapshot = []
    for loc in db.query(Location).filter(Location.is_active.is_(True)).all():
        waiting = db.query(Token).filter(
            Token.location_id == loc.id, Token.status == "waiting").count()
        serving = db.query(Token).filter(
            Token.location_id == loc.id, Token.status == "serving").count()
        called = db.query(Token).filter(
            Token.location_id == loc.id, Token.status == "called").count()
        counters = db.query(Counter).filter(
            Counter.location_id == loc.id,
            Counter.status == "open").order_by(Counter.id).all()

        now_serving = (
            db.query(Token)
            .filter(Token.location_id == loc.id,
                    Token.status.in_(("called", "serving")))
            .order_by(Token.called_at.desc().nullslast(), Token.number.desc())
            .first()
        )
        est = estimate_wait(loc, waiting)
        open_counters = len(counters)
        capacity = open_counters * (loc.overload_threshold or 5)
        label, key, pct = traffic_level(waiting, capacity)

        suggestion = {
            "Low": "Good time to go — book a token now.",
            "Moderate": "Normal rush — booking is fine.",
            "High": "Busy — expect a longer wait; consider a later slot.",
            "Very High": "Packed right now — avoid unless urgent.",
        }[label]

        snapshot.append({
            "location_id": loc.id, "name": loc.name, "code": loc.code,
            "category": loc.category, "operating_hours": loc.operating_hours,
            "waiting": waiting, "serving": serving, "called": called,
            "open_counters": open_counters,
            "total_counters": db.query(Counter)
                .filter(Counter.location_id == loc.id).count(),
            "capacity": capacity,
            "now_serving": now_serving.code if now_serving else None,
            "est_wait_minutes": est["estimated_wait_minutes"],
            "traffic_label": label, "traffic_key": key, "load_pct": round(pct),
            "suggestion": suggestion,
        })
    return snapshot


def kpis(db: Session) -> dict:
    today = datetime.utcnow().date()
    day_start = datetime.combine(today, datetime.min.time())

    base = db.query(Token)
    today_q = base.filter(Token.issued_at >= day_start)

    total_today = today_q.count()
    served_today = today_q.filter(Token.status == "completed").count()
    missed_today = today_q.filter(Token.status == "missed").count()
    waiting_now = db.query(Token).filter(Token.status == "waiting").count()
    serving_now = db.query(Token).filter(Token.status == "serving").count()

    avg_wait = (
        db.query(func.avg(Token.wait_minutes_actual))
        .filter(Token.wait_minutes_actual.is_not(None))
        .scalar()
    ) or 0.0
    csat = db.query(func.avg(Feedback.rating)).scalar() or 0.0
    open_counters = db.query(Counter).filter(Counter.status == "open").count()

    return {
        "tokens_today": total_today,
        "served_today": served_today,
        "missed_today": missed_today,
        "waiting_now": waiting_now,
        "serving_now": serving_now,
        "avg_wait_minutes": round(float(avg_wait), 1),
        "csat": round(float(csat), 2),
        "open_counters": open_counters,
        "active_locations": db.query(Location)
            .filter(Location.is_active.is_(True)).count(),
    }


def queue_volume_by_location(db: Session) -> list[dict]:
    rows = (
        db.query(Location.name, func.count(Token.id))
        .join(Token, Token.location_id == Location.id)
        .group_by(Location.name)
        .all()
    )
    return [{"location": name, "tokens": count} for name, count in rows]


def peak_hours(db: Session, days: int = 7) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(func.strftime("%H", Token.issued_at), func.count(Token.id))
        .filter(Token.issued_at >= since)
        .group_by(func.strftime("%H", Token.issued_at))
        .order_by(func.strftime("%H", Token.issued_at))
        .all()
    )
    return [{"hour": f"{h}:00", "tokens": c} for h, c in rows]


def counter_utilization(db: Session) -> list[dict]:
    counters = db.query(Counter).all()
    out = []
    for c in counters:
        served = (
            db.query(Token)
            .filter(Token.counter_id == c.id, Token.status == "completed")
            .count()
        )
        active = (
            db.query(Token)
            .filter(Token.counter_id == c.id, Token.status.in_(("waiting", "called", "serving")))
            .count()
        )
        out.append({
            "counter": c.name,
            "location_id": c.location_id,
            "status": c.status,
            "served_total": served,
            "active_load": active,
        })
    return out


def satisfaction_trend(db: Session, days: int = 7) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(func.date(Feedback.created_at), func.avg(Feedback.rating))
        .filter(Feedback.created_at >= since)
        .group_by(func.date(Feedback.created_at))
        .order_by(func.date(Feedback.created_at))
        .all()
    )
    return [{"date": d, "csat": round(float(r), 2)} for d, r in rows]


def missed_rate_trend(db: Session, days: int = 7) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    tokens = db.query(Token).filter(Token.issued_at >= since).all()
    buckets: dict[str, dict] = {}
    for t in tokens:
        key = t.issued_at.date().isoformat()
        b = buckets.setdefault(key, {"date": key, "total": 0, "missed": 0})
        b["total"] += 1
        if t.status == "missed":
            b["missed"] += 1
    return [
        {**b, "rate_pct": round(100.0 * b["missed"] / b["total"], 1)}
        for b in sorted(buckets.values(), key=lambda x: x["date"])
    ]
