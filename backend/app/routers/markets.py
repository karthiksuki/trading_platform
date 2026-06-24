from typing import Any

from fastapi import APIRouter

from app.services.markets import get_public_market as get_market_payload
from app.services.markets import list_public_markets as list_market_payloads

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("")
def list_public_markets(status: str = "OPEN", limit: int = 50) -> list[dict[str, Any]]:
    return list_market_payloads(status, limit)


@router.get("/{market_id}")
def get_public_market(market_id: int) -> dict[str, Any]:
    return get_market_payload(market_id)
