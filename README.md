# Trading App Template

Starter full-stack template for a trading app:
- Python backend (`FastAPI`)
- Frontend (`Vite + React + TypeScript`)

## Project Structure

```text
trading_platform/
  backend/
    app/main.py
    requirements.txt
  frontend/
    src/App.tsx
    ...
```

## Backend Setup

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API test:
- `GET http://localhost:8000/health`
- `GET http://localhost:8000/api/market/ticker`

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173` and proxies API requests to backend.

## Next Steps

- Add authentication and user portfolios
- Add order placement and order history endpoints
- Integrate live market data provider
