# QueueWise AI — Smart Queue Management & Virtual Token System

> **Full-stack Python implementation** of the SYNTRIX / LTM HackNow-2026 concept:
> virtual tokens, transparent wait-time prediction, intelligent counter load balancing,
> missed-token recovery, feedback/CSAT, and the Campus Queue Digital Command Center (CQ-DCC).

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite)
![Tests](https://img.shields.io/badge/Tests-17_passing-brightgreen?logo=pytest)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🎯 Problem → Solution

| Campus Pain Point | QueueWise AI Fix |
|-------------------|------------------|
| Blind queues — students don't know wait time | **Live Traffic Board** (`/traffic`) shows congestion level, queue length, est. wait for every service point |
| Paper tokens & verbal calling | **Virtual Token Engine** — remote booking, sequential codes (e.g. `TF-042`), full audit trail |
| Uneven counters — one packed, one empty | **Intelligent Load Balancing** auto-routes to least-loaded counter when threshold breached |
| No-shows stall the line | **3-min Grace Timer** → auto-mark Missed → call next → send Rejoin invite |
| Zero feedback loop | **Post-service CSAT** (1–5 + comment) linked to token/counter/staff/time |
| Admins guess staffing | **CQ-DCC Command Center** — live KPIs, peak-hour heatmap, counter utilization, satisfaction trends |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI App                               │
├─────────────────────────────────────────────────────────────────┤
│  Routers                                                         │
│  ├─ /auth        → login / register / logout                     │
│  ├─ /portal      → Student: live traffic, book token, my tokens │
│  ├─ /workspace   → Staff: call next, start, complete, no-show    │
│  ├─ /cqdcc       → Supervisor/Admin: KPIs, charts, management    │
│  ├─ /board       → Public NOW-SERVING display                   │
│  ├─ /traffic     → Public Traffic Board (decision support)       │
│  ├─ /api         → JSON REST (queues, traffic, tokens, kpis)    │
│  └─ /ws          → WebSocket hub (token_update, counter, cqdcc)  │
├─────────────────────────────────────────────────────────────────┤
│  Services                                                        │
│  ├─ token_engine   → numbering, prediction, LB, missed recovery │
│  ├─ analytics      → traffic snapshot, KPIs, charts data         │
│  ├─ notifications  → persistent log + WS broadcast              │
│  └─ scheduler      → grace-timer sweep (missed-token recovery)  │
├─────────────────────────────────────────────────────────────────┤
│  Data (SQLAlchemy + SQLite)                                      │
│  User / Location / Counter / QueueSession / Token / Feedback     │
│  NotificationLog                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

```bash
# 1. Clone & enter
git clone https://github.com/<your-username>/queuewise-ai.git
cd queuewise-ai

# 2. Create venv & install
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

# 3. Seed demo data (15 users, 5 locations, 8 counters, 377 tokens, 200 feedback)
python seed_data.py

# 4. Run server
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

### Demo Accounts (after seeding)

| Role | Email | Password |
|------|-------|----------|
| Student | `priya@student.edu` | `student123` |
| Staff | `ravi.staff@queuewise.ai` | `staff123` |
| Supervisor | `meena.sup@queuewise.ai` | `super123` |
| Admin | `admin@queuewise.ai` | `admin123` |

> Students can also self-register at `/register`.

---

## 🧪 Test Suite

```bash
pytest -q
# 17 passed
```

Covers: token engine (numbering, prediction, load balancing, missed recovery, rejoin), API auth/ACL, traffic endpoint, staff flow, feedback/CSAT.

---

## 📸 Key Screens (Descriptions)

- **Campus Traffic Board** (`/traffic`) — color-coded cards (Low/Moderate/High/Very High) with live capacity bars, waiting count, now-serving token, est. wait, and "Take Token" buttons.
- **Student Portal** (`/portal`) — live queue cards with traffic badges, "Track Location" toggle on token detail page.
- **Staff Workspace** (`/workspace`) — real-time queue, "Call Next", "Start", "Complete", "No-show" actions.
- **CQ-DCC** (`/cqdcc`) — KPI tiles, Chart.js bar charts (volume, peak hours, utilization, CSAT, missed rate), live notification feed.
- **Public Display Board** (`/board/<loc>`) — lobby-style NOW SERVING screen.

---

## 🛠️ Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | FastAPI 0.115 |
| Templates | Jinja2 (server-rendered) |
| Real-time | Native WebSocket (`/ws?topic=…`) |
| Database | SQLite + SQLAlchemy 2.0 |
| Auth | Session cookies (Starlette `SessionMiddleware`) + role-based ACL |
| Charts | Chart.js (CDN) on CQ-DCC |
| Testing | pytest + httpx `TestClient` |

---

## 🔧 Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `QUEUEWISE_DB` | `queuewise.db` | SQLite file path |
| `QUEUEWISE_SECRET` | dev secret | Session signing key |
| `QUEUEWISE_GRACE_SECONDS` | `180` | Missed-token grace window |
| `QUEUEWISE_THRESHOLD` | `5` | Counter overload threshold |
| `QUEUEWISE_SWEEP_SECONDS` | `5` | Scheduler sweep interval |

---

## 📁 Project Structure

```
queuewise-ai/
├── app/
│   ├── main.py              # FastAPI factory, lifespan, routes
│   ├── config.py            # Settings
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models.py            # ORM models (User, Location, Counter, Token, ...)
│   ├── auth.py              # Session auth + ACL dependencies
│   ├── templates_env.py     # Shared Jinja2Templates
│   ├── templates/           # base.html, portal, workspace, cqdcc, traffic, ...
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/ (common, portal, token, workspace, cqdcc, traffic)
│   ├── routers/
│   │   ├── auth_routes.py
│   │   ├── student.py
│   │   ├── staff.py
│   │   ├── admin.py
│   │   ├── board.py
│   │   ├── api.py
│   │   └── ws.py
│   └── services/
│       ├── token_engine.py
│       ├── analytics.py
│       ├── notifications.py
│       ├── ws.py
│       └── scheduler.py
├── seed_data.py             # Demo data generator
├── tests/
│   ├── conftest.py
│   ├── test_token_engine.py
│   └── test_api.py
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 📜 License

MIT — free to use, modify, and showcase on your résumé.

---

## 🙌 Credits

Concept: *Smart Queue Management & Virtual Token System*  
Python implementation: full-stack FastAPI + SQLite + WebSockets
