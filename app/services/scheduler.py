"""Background scheduler: sweeps grace timers (missed-token recovery).

ServiceNow equivalent: Flow Designer timer + SLA breach handling.
Runs every SWEEP_INTERVAL_SECONDS; any 'called' token whose grace window
expired is auto-marked MISSED and the counter automatically serves next.
"""
import asyncio
import contextlib

from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

from ..config import SWEEP_INTERVAL_SECONDS
from ..database import SessionLocal
from ..models import Token, utcnow
from .token_engine import expire_grace


async def sweep_grace_timers(factory: sessionmaker = SessionLocal):
    while True:
        try:
            db = factory()
            overdue = (
                db.query(Token)
                .filter(Token.status == "called",
                        Token.grace_expires_at.is_not(None),
                        or_(Token.grace_expires_at <= utcnow(),))
                .all()
            )
            for token in overdue:
                with contextlib.suppress(Exception):
                    expire_grace(db, token)
            db.close()
        except Exception:
            pass
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def start_scheduler(app):
    task = asyncio.create_task(sweep_grace_timers())
    app.state.scheduler_task = task
