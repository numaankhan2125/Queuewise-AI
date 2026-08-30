"""Auth pages: login, student self-registration, logout."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import authenticate, login_session, logout_session
from ..database import get_db
from ..models import User, hash_password
from ..templates_env import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = authenticate(db, email, password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid email or password"}, status_code=401)
    login_session(request, user)
    return RedirectResponse("/", status_code=302)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@router.post("/register")
def register(request: Request, name: str = Form(...), email: str = Form(...),
             roll_no: str = Form(""), password: str = Form(...),
             db: Session = Depends(get_db)):
    email = email.lower().strip()
    if len(password) < 6:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Password must be at least 6 characters"}, status_code=400)
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Email already registered"}, status_code=409)

    user = User(name=name.strip(), email=email, roll_no=roll_no.strip() or None,
                password_hash=hash_password(password), role="student")
    db.add(user)
    db.commit()
    login_session(request, user)
    return RedirectResponse("/portal", status_code=302)


@router.get("/logout")
def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=302)
