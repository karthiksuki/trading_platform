from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="trading_platform_backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/market/ticker")
def market_ticker() -> dict[str, str | float]:
    return {
        "symbol": "AAPL",
        "price": 192.45,
        "currency": "USD",
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
