"""Application factory: sessions, static, routes, startup hooks."""
import asyncio
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import SECRET_KEY, SESSION_MAX_AGE
from .database import get_db, init_db
from .auth import get_current_user
from .models import User
from .services.scheduler import sweep_grace_timers
from .services.ws import hub

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="QueueWise AI", version="1.0.0",
              description="Smart Queue Management & Virtual Token System")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY,
                   max_age=SESSION_MAX_AGE)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
async def on_startup():
    init_db()
    hub.bind_loop()
    app.state.scheduler_task = asyncio.create_task(sweep_grace_timers())


@app.on_event("shutdown")
async def on_shutdown():
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()


@app.get("/")
def home(user: User | None = Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=302)
    if user.role == "student":
        return RedirectResponse("/portal", status_code=302)
    if user.role == "staff":
        return RedirectResponse("/workspace", status_code=302)
    return RedirectResponse("/cqdcc", status_code=302)


# routers
from .routers import admin, api, auth_routes, board, staff, student, ws  # noqa: E402

app.include_router(auth_routes.router)
app.include_router(student.router)
app.include_router(staff.router)
app.include_router(admin.router)
app.include_router(board.router)
app.include_router(api.router)
app.include_router(ws.router)
