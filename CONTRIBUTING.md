# Contributing

Thanks for helping improve Trading Platform.

## Development Setup

Run the full app with Docker:

```bash
docker compose up --build
```

Or run services locally:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

## Workflow

1. Fork the repo.
2. Create a branch like `feature/market-card` or `fix/orderbook-refresh`.
3. Keep changes focused and small.
4. Update docs when setup, APIs, or behavior changes.
5. Open a pull request with a clear summary and test notes.

## Checks

Run these before opening a PR:

```bash
python -m py_compile backend/app/main.py
cd frontend && npm run lint && npm run build
```

## Pull Request Checklist

- The change has a clear reason.
- The app still builds.
- No secrets or `.env` files are committed.
- UI changes include screenshots when useful.
- New endpoints or commands are documented.
