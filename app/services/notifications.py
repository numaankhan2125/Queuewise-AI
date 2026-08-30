"""Notification service: persists every alert to NotificationLog and pushes
it live over WebSockets (portal alerts replace ServiceNow Notifications)."""
from sqlalchemy.orm import Session

from ..models import NotificationLog
from .ws import hub


def notify(db: Session, ntype: str, message: str,
           token_id: int | None = None, user_id: int | None = None,
           channel: str = "portal", extra: dict | None = None) -> NotificationLog:
    row = NotificationLog(
        token_id=token_id, user_id=user_id, type=ntype,
        message=message, channel=channel,
    )
    db.add(row)
    db.commit()
    hub.publish(["cqdcc"], "notification", {
        "notification": {
            "id": row.id, "type": ntype, "message": message,
            "token_id": token_id, "user_id": user_id,
        },
        **(extra or {}),
    })
    return row
