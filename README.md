# Trading Platform

A full-stack trading application with Web3 wallet authentication, order matching, payments, and an admin operations console. The stack is intentionally simple for local development: a **FastAPI** backend with **SQLite** runtime storage, and a **Vite + React + TypeScript** frontend with **Supabase Web3 auth**.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Backend](#backend)
- [Frontend](#frontend)
- [Admin Console](#admin-console)
- [Database](#database)
- [API Reference](#api-reference)
- [Development Workflow](#development-workflow)
- [Contributing](#contributing)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)

---

## Features

### Trader experience

- **Web3 sign-in** via Supabase (Ethereum or Solana wallets)
- **One-time onboarding** per wallet account (no duplicate onboarding history spam)
- **Trading**: market buy/sell, limit orders, merge/split positions
- **Limit-order matching engine** with partial fills, trade records, and atomic position/balance updates
- **Payments**: deposit/withdraw with idempotency keys
- **Dashboard**: trade controls, payments, history, open orders

### Admin experience

- **Dedicated admin login** (email + password) separate from wallet login
- **Session persistence** across page refresh (browser `localStorage`)
- **Market management**: create markets, open/pause/close status
- **Monitoring**: summary metrics, audit logs, market health
- **Operations**: stale order cleanup, reconciliation, risk exposure recalculation
- **User moderation**: freeze/unfreeze, role updates, manual balance adjustments

---

## Architecture

```text
┌─────────────────────┐         ┌──────────────────────────┐
│  React Frontend     │  proxy  │  FastAPI Backend         │
│  (localhost:5173)   │ ──────► │  (localhost:8000)        │
│                     │  /api   │                          │
│  - Wallet auth      │         │  - SQLite (trading.db)   │
│    (Supabase)       │         │  - Matching engine       │
│  - Admin console    │         │  - Admin APIs            │
└─────────┬───────────┘         └──────────────────────────┘
          │
          ▼
┌─────────────────────┐
│  Supabase Auth      │  (Web3 wallet sessions)
└─────────────────────┘

Optional (schema/migrations):
┌─────────────────────┐
│  PostgreSQL         │  via Prisma (Supabase)
└─────────────────────┘
```

The **runtime API** uses SQLite in `backend/trading.db`. Prisma + PostgreSQL in `frontend/prisma/` is available for extended schema work and Supabase-hosted Postgres, but the live FastAPI handlers currently read/write SQLite.

---

## Tech Stack

| Layer | Technology |
|--------|------------|
| Backend API | Python 3.11+, FastAPI, Pydantic, Uvicorn |
| Runtime DB | SQLite (`trading.db`) |
| Frontend | React 19, TypeScript, Vite 8 |
| UI motion | Framer Motion |
| Wallet auth | Supabase (`@supabase/supabase-js`) |
| Optional ORM | Prisma 6 + PostgreSQL (Supabase) |

---

## Prerequisites

- **Node.js** 20+ and **npm**
- **Python** 3.11+
- A **Supabase** project with Web3 auth enabled (for wallet login)
- Optional: **MetaMask** (Ethereum) or **Phantom/Backpack** (Solana) browser extension

---

## Project Structure

```text
trading_platform/
├── README.md                 # This file
├── backend/
│   ├── app/
│   │   └── main.py           # FastAPI app, matching engine, all REST routes
│   ├── requirements.txt
│   ├── trading.db            # Created on first run (gitignored)
│   └── .gitignore
└── frontend/
    ├── src/
    │   ├── App.tsx           # Wallet login, trader dashboard, routing
    │   ├── AdminPage.tsx     # Dedicated admin console
    │   └── supabase.ts       # Supabase client
    ├── prisma/
    │   ├── schema.prisma     # Postgres schema (optional migrations)
    │   └── migrations/
    ├── vite.config.ts        # Dev proxy → backend :8000
    ├── package.json
    └── .env                  # Local secrets (not committed)
```

---

## Quick Start

### 1. Clone and enter the repo

```bash
git clone <your-repo-url>
cd trading_platform
```

### 2. Start the backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify: [http://localhost:8000/health](http://localhost:8000/health) should return `{"status":"ok"}`.

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Configure frontend environment

Create `frontend/.env` (do not commit real secrets):

```env
VITE_SUPABASE_URL=https://<your-project>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<your-supabase-anon-or-publishable-key>

# Optional — only if using Prisma migrations against Supabase Postgres
DATABASE_URL=postgresql://...
DIRECT_URL=postgresql://...
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). API calls to `/api/*` are proxied to the backend (see `frontend/vite.config.ts`).

### 5. First-time usage

1. **Trader**: Click **Sign in with wallet (Ethereum)** or **Solana**, complete wallet signature, then finish onboarding once.
2. **Deposit** funds in the Payments tab before buying (USD balance is required for buys).
3. **Admin**: On the login screen, click **Admin**, sign in with an allowed admin email (see [Admin Console](#admin-console)).

---

## Environment Variables

### Frontend (`frontend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_SUPABASE_URL` | Yes | Supabase project URL |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Yes | Supabase publishable/anon key for client auth |
| `DATABASE_URL` | No | Prisma pooler URL (Supabase Postgres) |
| `DIRECT_URL` | No | Prisma direct URL for migrations |

### Backend

No `.env` file is required for the default SQLite setup. The database file `backend/trading.db` is created automatically on startup.

---

## Backend

### Running in production-like mode

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Core capabilities

- **Order matching**: limit orders match when best bid ≥ best ask; supports `PENDING`, `PARTIAL`, `FILLED`, `CANCELLED`
- **Atomic updates**: fills update orders, trades, positions, and USD cash balances in one locked transaction
- **Idempotent payments**: `Idempotency-Key` header on deposit/withdraw
- **Admin guard**: admin routes validate email + password against `admin_emails` table

### Default dev admin account

On startup, the backend seeds one admin row (development only):

| Email | Password |
|-------|----------|
| `karcode95@gmail.com` | `testin@test` |

Change or remove this in production. Do not ship default credentials to a public deployment.

### SQLite tables (runtime)

Created/migrated at startup: `orders`, `positions`, `history`, `payment_transactions`, `cash_balances`, `idempotency_keys`, `users`, `admin_emails`, `trades`, `markets`.

---

## Frontend

### Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server (port 5173) |
| `npm run build` | Typecheck + production build |
| `npm run preview` | Preview production build |
| `npm run lint` | Run ESLint |
| `npm run prisma:generate` | Generate Prisma client |
| `npm run prisma:migrate` | Run Prisma migrations (Postgres) |
| `npm run prisma:push` | Push schema to Postgres without migration files |

### App modes

| Mode | Entry | Persistence |
|------|--------|-------------|
| Trader | Wallet sign-in + onboarding | Supabase session |
| Admin | Admin login → `access_grant` | `localStorage` key `trading_platform_admin_session` |

Use **Exit Admin** or **Sign out** to clear stored admin session.

---

## Admin Console

After successful admin login, the app opens **AdminPage** with:

- **Monitoring**: open orders, trades (1h/24h), frozen users, failure counts
- **Audit logs**: filterable history stream
- **Market controls**: create symbol, set OPEN / PAUSED / CLOSED
- **Operations**: stale order cleanup, reconciliation mismatches, top risk exposures

All admin API calls require `admin_email` and `admin_password` (query params for GET, JSON body for POST).

---

## Database

### SQLite (primary for API)

- File: `backend/trading.db`
- Gitignored; safe to delete for a clean local reset (restart backend to recreate schema)

### Prisma + PostgreSQL (optional)

Use when you want Supabase-hosted Postgres aligned with `frontend/prisma/schema.prisma`:

```bash
cd frontend
npm run prisma:generate
npm run prisma:migrate -- --name init
# or: npm run prisma:push
```

Models include `users`, `markets`, `orders`, `trades`, `positions`, `wallet_balances`, `history_events`, `idempotency_keys`, etc.

---

## API Reference

Base URL (direct): `http://localhost:8000`  
Via frontend dev proxy: `http://localhost:5173/api/...`

### Health & market

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/market/ticker` | Sample ticker payload |

### Trading

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/trading/buy` | Market buy |
| POST | `/api/trading/sell` | Market sell |
| POST | `/api/trading/limit` | Place limit order (auto-match) |
| POST | `/api/trading/merge` | Merge positions across markets |
| POST | `/api/trading/split` | Split position legs |
| GET | `/api/trading/history` | User/market history |
| GET | `/api/trading/open-orders` | Open/partial orders |
| GET | `/api/trading/orderbooks/{market_id}` | Aggregated book |
| GET | `/api/trading/trades` | Recent trades |

### Payments

| Method | Path | Headers | Description |
|--------|------|---------|-------------|
| POST | `/api/payments/deposit` | `Idempotency-Key` (optional) | Credit balance |
| POST | `/api/payments/withdraw` | `Idempotency-Key` (optional) | Debit balance |
| GET | `/api/payments/transactions` | — | List transactions |
| GET | `/api/payments/balances/{user_id}` | — | Cash balances |

### Users

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/users/onboard` | Create user (idempotent per `user_id`) |
| GET | `/api/users/{user_id}` | Fetch profile |

### Admin

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/access_grant` | Admin login gate |
| GET | `/api/admin/overview` | Stats + recent users |
| POST | `/api/admin/markets` | Create market |
| GET | `/api/admin/markets` | List markets |
| POST | `/api/admin/markets/{id}/status` | OPEN / PAUSED / CLOSED |
| GET | `/api/admin/monitoring/summary` | Dashboard metrics |
| GET | `/api/admin/monitoring/logs` | Filtered audit logs |
| GET | `/api/admin/monitoring/market-health` | Per-market spread/last trade |
| POST | `/api/admin/ops/stale-order-cleanup` | Cancel old open orders |
| POST | `/api/admin/ops/reconcile` | Position vs trade consistency |
| POST | `/api/admin/ops/risk-recalc` | Top exposure users |
| POST | `/api/admin/users/freeze` | Freeze/unfreeze account |
| POST | `/api/admin/users/role` | Grant/revoke admin flag on user |
| POST | `/api/admin/balances/adjust` | Manual balance adjustment |

Example deposit body:

```json
{
  "user_id": "wallet:<address>",
  "asset": "USD",
  "amount": 100,
  "reference": "ui-deposit"
}
```

---

## Development Workflow

### Recommended local setup

1. Terminal 1: `uvicorn app.main:app --reload --port 8000` (from `backend/`)
2. Terminal 2: `npm run dev` (from `frontend/`)

### Code style

- **Backend**: keep route handlers thin; use existing `DB_LOCK` + connection helpers for writes
- **Frontend**: prefer `callApi` helper; surface user-friendly errors (not raw JSON blobs)
- **Commits**: small, focused changes with clear messages

### Reset local data

```bash
# Stop backend, then:
rm backend/trading.db backend/trading.db-wal backend/trading.db-shm
# Restart backend — schema and seed admin row are recreated
```

### Build for production

```bash
cd frontend && npm run build
# Serve frontend/dist/ with any static host; ensure /api proxies to backend
```

---

## Contributing

We welcome contributions. Please follow this flow:

### 1. Fork and branch

```bash
git checkout -b feature/your-short-description
```

Use prefixes: `feature/`, `fix/`, `docs/`, `chore/`.

### 2. Make changes

- Match existing patterns in `backend/app/main.py` and `frontend/src/`
- Avoid unrelated refactors in the same PR
- Update this README if you add env vars, endpoints, or setup steps

### 3. Verify before opening a PR

```bash
# Backend
cd backend && python -m py_compile app/main.py

# Frontend
cd frontend && npm run lint && npm run build
```

### 4. Pull request checklist

- [ ] Description explains **what** and **why**
- [ ] Setup/docs updated if behavior or config changed
- [ ] No secrets committed (`.env`, keys, passwords)
- [ ] Tested locally (wallet flow and/or admin flow as relevant)

### 5. Reporting issues

Include:

- OS and browser/wallet used
- Steps to reproduce
- Expected vs actual behavior
- Relevant API response or console error (redact secrets)

### Code of conduct

Be respectful and constructive. Harassment or discrimination is not tolerated.

---

## Security Notes

- **Do not commit** `frontend/.env` or `backend/.env` — they are gitignored
- Default admin credentials are for **local development only**
- Admin passwords are stored in plaintext in SQLite today — replace with hashed passwords + JWT/session tokens before production
- Wallet auth is handled by Supabase; backend does not yet verify Supabase JWT on every trading route
- CORS is restricted to `http://localhost:5173` in development — update for your deployment origin

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|----------------|-----|
| `Insufficient position quantity to sell` | No position for that market | Buy first, or lower sell quantity |
| `Insufficient USD balance for buy` | Zero cash balance | Deposit in Payments tab |
| Raw JSON error on deposit | Malformed body / proxy issue | Use UI buttons; ensure backend is running on :8000 |
| Wallet login fails | Missing Supabase env | Set `VITE_SUPABASE_*` in `frontend/.env` |
| Admin session lost on refresh | Old build without persistence | Pull latest; check `localStorage` key after login |
| API 404 from frontend | Backend not running | Start Uvicorn on port 8000 |
| Duplicate onboarding entries | Fixed in current backend | Existing users return `status: "exists"` |

---

## Roadmap

High-impact items not yet fully implemented:

- JWT verification for Supabase sessions on backend routes
- Hashed admin passwords and short-lived admin tokens
- Global idempotency on all mutating trading endpoints
- Risk guardrails (max position, daily loss, margin checks)
- Portfolio analytics (PnL, exposure, performance timeline)
- Background jobs (settlement, reconciliation cron, stale order sweeps)
- Structured logging and metrics dashboards

---

## License

Specify your license here (e.g. MIT). If unset, contact the repository owner for usage terms.

---

## Acknowledgments

Built with [FastAPI](https://fastapi.tiangolo.com/), [Vite](https://vite.dev/), [React](https://react.dev/), and [Supabase](https://supabase.com/).
