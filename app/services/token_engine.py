"""Virtual Token Engine - the heart of QueueWise AI.

Implements (mapped from the SYNTRIX ServiceNow design):
    * Virtual Token Engine      -> sequential daily tokens w/ full audit trail
    * Transparent wait-time AI  -> queue_length x historical avg service time,
                                   inputs stored on the token record itself
    * Intelligent Load Balancing-> least-loaded active counter routing +
                                   supervisor overload alerts
    * Missed-Token Recovery     -> grace timer expiry -> Missed -> auto call
                                   next -> rejoin invite
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..config import COUNTER_OVERLOAD_THRESHOLD, GRACE_SECONDS, PROXIMITY_POSITION
from ..models import Counter, Location, QueueSession, Token, utcnow
from .notifications import notify
from .ws import hub, topics_for_token

ACTIVE_STATES = ("waiting", "called", "serving")


# ---------------------------------------------------------------- prediction
def estimate_wait(location: Location, waiting_count: int) -> dict:
    """Transparent estimate - every input returned so the UI can display it."""
    avg = float(location.avg_service_minutes or 0)
    minutes = round(waiting_count * avg, 1)
    return {
        "queue_length": waiting_count,
        "avg_service_time_min": avg,
        "estimated_wait_minutes": minutes,
        "formula": f"{waiting_count} x {avg:.1f} min = {minutes} min",
    }


def _live_estimate(db: Session, location: Location) -> dict:
    waiting = (
        db.query(Token)
        .filter(Token.location_id == location.id, Token.status == "waiting")
        .count()
    )
    return estimate_wait(location, waiting)


# ------------------------------------------------------------ load balancing
def counter_load(db: Session, counter_id: int) -> int:
    return (
        db.query(Token)
        .filter(Token.counter_id == counter_id, Token.status.in_(ACTIVE_STATES))
        .count()
    )


def choose_counter(db: Session, location: Location) -> tuple[Counter, bool]:
    """Return (counter, was_rerouted).

    Picks the least-loaded OPEN counter. Reroute is flagged when the
    location's primary counter breaches its overload threshold while another
    counter sits lighter - triggers a supervisor alert upstream.
    """
    counters = (
        db.query(Counter)
        .filter(Counter.location_id == location.id, Counter.status == "open")
        .order_by(Counter.id)
        .all()
    )
    if not counters:
        raise ValueError("No open counters at this location")

    loads = {c.id: counter_load(db, c.id) for c in counters}
    chosen = min(counters, key=lambda c: (loads[c.id], c.id))
    primary = counters[0]

    threshold = location.overload_threshold or COUNTER_OVERLOAD_THRESHOLD
    rerouted = chosen.id != primary.id and loads[primary.id] >= threshold
    return chosen, rerouted


# ------------------------------------------------------------- token issuing
def _next_number(db: Session, location: Location) -> tuple[int, str]:
    session = (
        db.query(QueueSession)
        .filter(QueueSession.location_id == location.id,
                QueueSession.session_date == date.today())
        .first()
    )
    if session is None:
        session = QueueSession(location_id=location.id)
        db.add(session)
        db.flush()
    session.last_number += 1
    return session.last_number, f"{location.code}-{session.last_number:03d}"


def _issue(db: Session, *, student_id: int, location: Location,
           service_type: str, rejoined_from: int | None = None,
           rerouted: bool = False) -> Token:
    counter, rerouted = choose_counter(db, location)
    number, code = _next_number(db, location)

    # transparent prediction inputs captured at booking time
    pred = _live_estimate(db, location)

    token = Token(
        code=code, number=number,
        location_id=location.id, counter_id=counter.id,
        student_id=student_id, service_type=service_type,
        queue_len_at_booking=pred["queue_length"],
        avg_service_time_used=pred["avg_service_time_min"],
        est_wait_minutes=pred["estimated_wait_minutes"],
        rejoined_from_token=rejoined_from,
    )
    db.add(token)
    db.commit()

    notify(db, "booking",
           f"Token {code} booked at {location.name} ({counter.name}). "
           f"Estimated wait {pred['estimated_wait_minutes']} min.",
           token_id=token.id, user_id=student_id,
           extra={"token": _dto(token), "event": "booked"})

    if rerouted:
        notify(db, "supervisor",
               f"Load balancing: {location.name} primary counter overloaded "
               f"(threshold {location.overload_threshold}); new tokens routed "
               f"to {counter.name}.",
               token_id=token.id,
               extra={"token": _dto(token), "event": "reroute"})

    hub.publish(topics_for_token(token), "token_update", {
        "token": _dto(token), "event": "booked"})
    return token


def create_token(db: Session, *, student_id: int, location_id: int,
                 service_type: str = "general") -> Token:
    location = db.get(Location, location_id)
    if location is None or not location.is_active:
        raise ValueError("Location unavailable")

    # one active token per student per location keeps queues fair
    dup = (
        db.query(Token)
        .filter(Token.student_id == student_id,
                Token.location_id == location.id,
                Token.status.in_(ACTIVE_STATES))
        .first()
    )
    if dup:
        raise ValueError(f"You already hold active token {dup.code} here")

    token = _issue(db, student_id=student_id, location=location,
                   service_type=service_type)
    _maybe_proximity_alert(db, token.location_id)
    return token


# --------------------------------------------------------------- queue reads
def waiting_tokens(db: Session, counter_id: int) -> list[Token]:
    return (
        db.query(Token)
        .filter(Token.counter_id == counter_id, Token.status == "waiting")
        .order_by(Token.number)
        .all()
    )


def position_of(token: Token, db: Session) -> int:
    if token.status != "waiting":
        return 0
    ahead = waiting_tokens(db, token.counter_id)
    return ahead.index(token) + 1 if token in ahead else 0


def _maybe_proximity_alert(db: Session, location_id: int):
    """Fire 'almost your turn' alerts when a student sits at position N."""
    counters = db.query(Counter).filter(
        Counter.location_id == location_id, Counter.status == "open").all()
    for c in counters:
        for pos, tok in enumerate(waiting_tokens(db, c.id), start=1):
            if pos == PROXIMITY_POSITION:
                notify(db, "proximity",
                       f"You are #{pos} in queue ({tok.code}). Please head to "
                       f"{c.name} now.",
                       token_id=tok.id, user_id=tok.student_id,
                       extra={"token": _dto(tok), "event": "proximity"})


# -------------------------------------------------------------- serving flow
def call_next(db: Session, counter: Counter, auto: bool = False) -> Token | None:
    queue = waiting_tokens(db, counter.id)
    nxt = queue[0] if queue else None
    if nxt is None:
        return None

    now = utcnow()
    nxt.status = "called"
    nxt.called_at = now
    nxt.grace_expires_at = now + timedelta(seconds=GRACE_SECONDS)
    db.commit()

    src = "auto" if auto else "staff"
    notify(db, "turn",
           f"NOW SERVING {nxt.code} at {counter.name}. Grace period "
           f"{GRACE_SECONDS // 60} min - please arrive before it expires.",
           token_id=nxt.id, user_id=nxt.student_id,
           extra={"token": _dto(nxt), "event": "called", "source": src})
    hub.publish(topics_for_token(nxt), "token_update", {
        "token": _dto(nxt), "event": "called", "source": src})
    _maybe_proximity_alert(db, counter.location_id)
    return nxt


def start_service(db: Session, token: Token) -> Token:
    if token.status != "called":
        raise ValueError("Token is not in called state")
    token.status = "serving"
    token.served_at = utcnow()
    token.grace_expires_at = None
    if token.called_at:
        mins = (token.served_at - token.called_at).total_seconds() / 60.0
        token.wait_minutes_actual = round(mins, 2)
    db.commit()
    hub.publish(topics_for_token(token), "token_update", {
        "token": _dto(token), "event": "serving"})
    return token


def complete_service(db: Session, token: Token) -> Token:
    if token.status != "serving":
        raise ValueError("Token is not being served")
    token.status = "completed"
    token.completed_at = utcnow()
    if token.served_at:
        mins = (token.completed_at - token.served_at).total_seconds() / 60.0
        token.service_minutes_actual = round(mins, 2)
        # rolling historical average feeds future predictions (EMA k=5)
        loc = token.location
        prev = loc.avg_service_minutes or mins
        loc.avg_service_minutes = round((prev * 4 + mins) / 5.0, 2)
    db.commit()

    notify(db, "feedback_invite",
           f"Service complete for {token.code}. Please rate your experience.",
           token_id=token.id, user_id=token.student_id,
           extra={"token": _dto(token), "event": "completed"})
    hub.publish(topics_for_token(token), "token_update", {
        "token": _dto(token), "event": "completed"})
    return token


def cancel_token(db: Session, token: Token, by_student: bool = True) -> Token:
    if token.status not in ACTIVE_STATES:
        raise ValueError("Token already closed")
    token.status = "cancelled"
    db.commit()
    who = "student" if by_student else "staff"
    notify(db, "cancelled", f"Token {token.code} cancelled by {who}.",
           token_id=token.id, user_id=token.student_id,
           extra={"token": _dto(token), "event": "cancelled"})
    hub.publish(topics_for_token(token), "token_update", {
        "token": _dto(token), "event": "cancelled"})
    _maybe_proximity_alert(db, token.location_id)
    return token


# ------------------------------------------------------ missed-token recovery
def expire_grace(db: Session, token: Token) -> Token | None:
    """Grace expired: mark MISSED, recover the counter, invite rejoin."""
    if token.status != "called":
        return None
    token.status = "missed"
    token.missed_at = utcnow()
    token.grace_expires_at = None
    db.commit()

    notify(db, "missed",
           f"Token {token.code} marked MISSED (no-show within grace period).",
           token_id=token.id, user_id=token.student_id,
           extra={"token": _dto(token), "event": "missed"})
    notify(db, "rejoin",
           f"Missed your turn ({token.code})? You can rejoin the "
           f"{token.location.name} queue from My Tokens.",
           token_id=token.id, user_id=token.student_id,
           extra={"token": _dto(token), "event": "rejoin_invite"})

    # counter never idles: immediately serve the next waiting token
    recovered = call_next(db, token.counter, auto=True)
    hub.publish(topics_for_token(token), "token_update", {
        "token": _dto(token), "event": "missed"})
    return recovered


def rejoin_queue(db: Session, token: Token) -> Token:
    """Student accepts the rejoin invite -> fresh token linked to old one."""
    if token.status != "missed":
        raise ValueError("Only missed tokens can be rejoined")
    fresh = _issue(db, student_id=token.student_id,
                   location=token.location, service_type=token.service_type,
                   rejoined_from=token.id)
    notify(db, "rejoined",
           f"Rejoined {fresh.location.name} with new token {fresh.code}.",
           token_id=fresh.id, user_id=fresh.student_id,
           extra={"token": _dto(fresh), "event": "booked"})
    return fresh


# -------------------------------------------------------------- serialization
def _dto(t: Token) -> dict:
    def iso(dt):
        return dt.isoformat() + "Z" if dt else None

    return {
        "id": t.id, "code": t.code, "number": t.number,
        "status": t.status, "service_type": t.service_type,
        "location_id": t.location_id, "counter_id": t.counter_id,
        "est_wait_minutes": t.est_wait_minutes,
        "grace_expires_at": iso(t.grace_expires_at),
        "issued_at": iso(t.issued_at),
    }
