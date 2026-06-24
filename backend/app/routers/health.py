from fastapi import APIRouter

from app.core.time import utc_now

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/market/ticker")
def market_ticker() -> dict[str, str | float]:
    return {
        "symbol": "AAPL",
        "price": 192.45,
        "currency": "USD",
        "as_of": utc_now(),
    }
