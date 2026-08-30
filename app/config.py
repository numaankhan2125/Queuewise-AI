"""Central application settings (12-factor style, overridable via env)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = os.getenv("QUEUEWISE_DB", str(BASE_DIR / "queuewise.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

SECRET_KEY = os.getenv("QUEUEWISE_SECRET", "queuewise-dev-secret-change-me")
SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

# Missed-token recovery: grace period after a token is called.
GRACE_SECONDS = int(os.getenv("QUEUEWISE_GRACE_SECONDS", "180"))

# Load balancing: a counter is overloaded when waiting tokens exceed this.
COUNTER_OVERLOAD_THRESHOLD = int(os.getenv("QUEUEWISE_THRESHOLD", "5"))

# Proximity alert fires when the student is this many positions from the front.
PROXIMITY_POSITION = 3

# Background scheduler sweep interval for grace timers.
SWEEP_INTERVAL_SECONDS = float(os.getenv("QUEUEWISE_SWEEP_SECONDS", "5"))

ROLES = ("student", "staff", "supervisor", "admin")

SERVICE_TYPES = {
    "general": "General Enquiry",
    "fee": "Fee Payment",
    "document": "Document Issue",
    "meal": "Meal Service",
}
