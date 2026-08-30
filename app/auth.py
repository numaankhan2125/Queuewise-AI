"""Session-cookie auth + role-based access control (ACL equivalent).

Roles: student, staff, supervisor, admin.  Dependencies below act as the
application's ACL layer: students only touch their own tokens, staff only
their counter queue, supervisors/admins get operational views.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import SESSION_MAX_AGE
from .database import get_db
from .models import User, verify_password

SESSION_KEY = "user_id"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_KEY)
    if not user_id:
        return None
    return db.get(User, user_id)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Not allowed for your role")
        return user

    return checker


require_student = require_role("student")
require_staff = require_role("staff", "supervisor", "admin")
require_supervisor = require_role("supervisor", "admin")
require_admin = require_role("admin")


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if user and user.is_active and verify_password(password, user.password_hash):
        return user
    return None


def login_session(request: Request, user: User):
    request.session[SESSION_KEY] = user.id


def logout_session(request: Request):
    request.session.clear()
