"""Data model: Users/Roles (ACL), Locations, Counters, QueueSessions,
Tokens (full lifecycle), Feedback and NotificationLog."""
import hashlib
import os
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 120_000
        )
        return digest.hex() == digest_hex
    except ValueError:
        return False


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20), index=True)  # student/staff/supervisor/admin
    roll_no: Mapped[str | None] = mapped_column(String(40))
    counter_id: Mapped[int | None] = mapped_column(ForeignKey("counters.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    counter: Mapped["Counter | None"] = relationship(
        foreign_keys=[counter_id])


class Location(Base):
    """Service location: cafeteria, fee counter, library desk, ..."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # token prefix e.g. FC
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")
    operating_hours: Mapped[str] = mapped_column(String(80), default="09:00-17:00")
    avg_service_minutes: Mapped[float] = mapped_column(Float, default=4.0)
    overload_threshold: Mapped[int] = mapped_column(Integer, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    counters: Mapped[list["Counter"]] = relationship(back_populates="location")


class Counter(Base):
    __tablename__ = "counters"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/closed
    staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    location: Mapped["Location"] = relationship(back_populates="counters")
    staff_user: Mapped["User | None"] = relationship(
        foreign_keys=[staff_user_id])


class QueueSession(Base):
    """One operating day per location; owns the daily sequential numbering."""

    __tablename__ = "queue_sessions"
    __table_args__ = (UniqueConstraint("location_id", "session_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    session_date: Mapped[date] = mapped_column(default=date.today)
    last_number: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Token(Base):
    """The virtual token: complete auditable lifecycle record."""

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)  # e.g. FC-042
    number: Mapped[int] = mapped_column(Integer)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    counter_id: Mapped[int] = mapped_column(ForeignKey("counters.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    service_type: Mapped[str] = mapped_column(String(30), default="general")

    # lifecycle: waiting -> called -> serving -> completed | missed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)

    # Transparent wait-time prediction inputs (verifiable by design).
    queue_len_at_booking: Mapped[int] = mapped_column(Integer, default=0)
    avg_service_time_used: Mapped[float] = mapped_column(Float, default=0.0)
    est_wait_minutes: Mapped[float] = mapped_column(Float, default=0.0)

    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    called_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    grace_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    served_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    missed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    wait_minutes_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_minutes_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerouted_from_counter: Mapped[int | None] = mapped_column(ForeignKey("counters.id"), nullable=True)
    rejoined_from_token: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), nullable=True)

    location: Mapped["Location"] = relationship()
    counter: Mapped["Counter"] = relationship(foreign_keys=[counter_id])
    student: Mapped["User"] = relationship()


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), unique=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1..5 CSAT
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    token: Mapped["Token"] = relationship()


class NotificationLog(Base):
    """Every automated alert the system emits (booking/proximity/turn/reroute/...)."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(40))  # booking/proximity/turn/reroute/missed/rejoin/supervisor
    message: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), default="portal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
