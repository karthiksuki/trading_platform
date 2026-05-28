# Trading Platform

Full-stack trading app: **FastAPI + SQLite** backend, **React + Vite** frontend, **Supabase Web3** wallet auth, and a dedicated **admin console**.

## Stack

- Backend: Python 3.11+, FastAPI, Uvicorn, SQLite (`backend/trading.db`)
- Frontend: React 19, TypeScript, Vite (proxies `/api` → `:8000`)
- Auth: Supabase Web3 (Ethereum / Solana)
- Optional: Prisma + PostgreSQL (`frontend/prisma/`) for schema migrations

## Quick start

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```env
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<your-key>
```

```bash
npm run dev
```

- App: http://localhost:5173  
- API health: http://localhost:8000/health  
- API docs: http://localhost:8000/docs  

## Usage

1. Sign in with an Ethereum or Solana wallet.
2. Complete onboarding once per wallet.
3. **Deposit USD** (Payments tab) before buying.
4. Trade: buy / sell / limit; view history and open orders.
5. **Admin**: login screen → **Admin** → email/password (`access_grant`). Session persists in `localStorage` until exit/sign out.

## Project layout

```text
trading_platform/
  backend/app/main.py    # API, matching engine, admin routes
  frontend/src/App.tsx   # Trader UI
  frontend/src/AdminPage.tsx
  frontend/prisma/       # Optional Postgres schema
```

## Main API groups

| Area | Examples |
|------|----------|
| Trading | `POST /api/trading/buy`, `sell`, `limit`, `merge`, `split` |
| Data | `GET /api/trading/history`, `open-orders`, `trades` |
| Payments | `POST /api/payments/deposit`, `withdraw` (optional `Idempotency-Key`) |
| Users | `POST /api/users/onboard`, `GET /api/users/{user_id}` |
| Admin | `POST /api/admin/access_grant`, markets, monitoring, ops, moderation |

## Contributing

1. Fork and branch: `feature/…`, `fix/…`, or `docs/…`
2. Change only what’s needed; match existing code style.
3. Verify locally:

```bash
cd backend && python -m py_compile app/main.py
cd frontend && npm run build
```

4. Open a PR with a clear description. Do not commit `.env` or secrets.

## Notes

- Runtime data lives in SQLite; delete `backend/trading.db` to reset locally.
- Default dev admin is seeded on backend startup—change before any public deploy.
- Sell requires an existing position; buy requires sufficient USD balance.

## License

Add your license (e.g. MIT) or contact the repo owner.
