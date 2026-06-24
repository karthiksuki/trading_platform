import json
import sqlite3
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.core.config import settings
from app.core.database import get_connection
from app.core.time import utc_now


def serialize_order_levels(rows: list[sqlite3.Row]) -> list[dict[str, float]]:
    return [
        {"price": float(row["price"]), "quantity": float(row["total_quantity"])}
        for row in rows
        if float(row["total_quantity"] or 0) > 0
    ]


def fetch_orderbook_for_outcome(connection: sqlite3.Connection, market_id: int, outcome: str) -> dict[str, Any]:
    buy_rows = connection.execute(
        """
        SELECT price, SUM(quantity - COALESCE(filled_quantity, 0)) as total_quantity
        FROM orders
        WHERE market_id = ?
          AND outcome = ?
          AND side = 'BUY'
          AND order_type = 'LIMIT'
          AND status IN ('PENDING', 'PARTIAL')
        GROUP BY price
        ORDER BY price DESC
        """,
        (market_id, outcome),
    ).fetchall()
    sell_rows = connection.execute(
        """
        SELECT price, SUM(quantity - COALESCE(filled_quantity, 0)) as total_quantity
        FROM orders
        WHERE market_id = ?
          AND outcome = ?
          AND side = 'SELL'
          AND order_type = 'LIMIT'
          AND status IN ('PENDING', 'PARTIAL')
        GROUP BY price
        ORDER BY price ASC
        """,
        (market_id, outcome),
    ).fetchall()
    bids = serialize_order_levels(buy_rows)
    asks = serialize_order_levels(sell_rows)
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": bids[0]["price"] if bids else None,
        "best_ask": asks[0]["price"] if asks else None,
    }


def serialize_market(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    market_id = int(row["id"])
    yes_book = fetch_orderbook_for_outcome(connection, market_id, "YES")
    no_book = fetch_orderbook_for_outcome(connection, market_id, "NO")
    last_trade = connection.execute(
        """
        SELECT t.created_at, t.execution_price, o.outcome
        FROM trades t
        JOIN orders o ON o.id = t.buy_order_id
        WHERE t.market_id = ?
        ORDER BY t.created_at DESC
        LIMIT 1
        """,
        (market_id,),
    ).fetchone()
    question = str(row["question"] or row["name"])
    return {
        "id": market_id,
        "market_id": market_id,
        "symbol": str(row["symbol"]),
        "name": str(row["name"]),
        "question": question,
        "description": str(row["description"] or ""),
        "status": str(row["status"]),
        "tick_size": float(row["tick_size"]),
        "min_order_size": float(row["min_order_size"]),
        "market_type": str(row["market_type"] or "BINARY"),
        "resolved_outcome": row["resolved_outcome"],
        "resolved_at": row["resolved_at"],
        "outcomes": {"YES": yes_book, "NO": no_book},
        "last_trade_at": str(last_trade["created_at"]) if last_trade else None,
        "last_trade_price": float(last_trade["execution_price"]) if last_trade else None,
        "last_trade_outcome": str(last_trade["outcome"]) if last_trade else None,
    }


def parse_polymarket_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def fetch_polymarket_json(path: str, params: dict[str, Any] | None = None) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{settings.polymarket_gamma_url.rstrip('/')}{path}{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 trading-platform/0.1",
        },
    )
    with urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_polymarket_market(item: dict[str, Any]) -> dict[str, Any] | None:
    outcomes = [str(outcome).upper() for outcome in parse_polymarket_json_list(item.get("outcomes"))]
    prices = [
        safe_float(price)
        for price in parse_polymarket_json_list(item.get("outcomePrices") or item.get("outcome_prices"))
    ]
    if "YES" not in outcomes or "NO" not in outcomes or len(prices) < len(outcomes):
        return None

    price_by_outcome = {outcome: prices[index] for index, outcome in enumerate(outcomes) if index < len(prices)}
    yes_price = price_by_outcome.get("YES", 0.0)
    no_price = price_by_outcome.get("NO", 0.0)
    liquidity = safe_float(item.get("liquidity"), 1.0)
    quantity = max(liquidity, 1.0)
    market_id = int(str(item["id"]))
    yes_book = {
        "bids": [{"price": yes_price, "quantity": quantity}] if yes_price > 0 else [],
        "asks": [{"price": yes_price, "quantity": quantity}] if yes_price > 0 else [],
        "best_bid": yes_price if yes_price > 0 else None,
        "best_ask": yes_price if yes_price > 0 else None,
    }
    no_book = {
        "bids": [{"price": no_price, "quantity": quantity}] if no_price > 0 else [],
        "asks": [{"price": no_price, "quantity": quantity}] if no_price > 0 else [],
        "best_bid": no_price if no_price > 0 else None,
        "best_ask": no_price if no_price > 0 else None,
    }
    question = str(item.get("question") or item.get("title") or item.get("slug") or f"Polymarket {market_id}")
    return {
        "id": market_id,
        "market_id": market_id,
        "external_id": str(item["id"]),
        "source": "polymarket",
        "symbol": str(item.get("slug") or f"POLY-{market_id}")[:30].upper(),
        "name": question,
        "question": question,
        "description": str(item.get("description") or "Live Polymarket market data. Trading in this app remains local demo trading."),
        "status": "OPEN" if item.get("active") and not item.get("closed") else "CLOSED",
        "tick_size": safe_float(item.get("minimumTickSize"), 0.01),
        "min_order_size": safe_float(item.get("minimumOrderSize"), 1.0),
        "market_type": "BINARY",
        "resolved_outcome": None,
        "resolved_at": None,
        "outcomes": {"YES": yes_book, "NO": no_book},
        "last_trade_at": None,
        "last_trade_price": safe_float(item.get("lastTradePrice"), 0.0) or None,
        "last_trade_outcome": None,
        "volume": safe_float(item.get("volume")),
        "liquidity": liquidity,
    }


def fetch_polymarket_markets(limit: int) -> list[dict[str, Any]]:
    raw = fetch_polymarket_json(
        "/markets",
        {
            "active": "true",
            "closed": "false",
            "limit": max(1, min(limit, 100)),
        },
    )
    items = raw if isinstance(raw, list) else raw.get("data", [])
    markets: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("enableOrderBook") is False:
            continue
        normalized = normalize_polymarket_market(item)
        if normalized:
            markets.append(normalized)
    return markets


def fetch_polymarket_market(market_id: int) -> dict[str, Any] | None:
    raw = fetch_polymarket_json(f"/markets/{market_id}")
    if not isinstance(raw, dict):
        return None
    return normalize_polymarket_market(raw)


def list_local_markets(status: str, limit: int) -> list[dict[str, Any]]:
    with get_connection() as connection:
        query = """
            SELECT id, symbol, name, question, description, status, tick_size, min_order_size,
                   market_type, resolved_outcome, resolved_at, created_at, updated_at
            FROM markets
        """
        args: list[Any] = []
        if status:
            query += " WHERE status = ?"
            args.append(status.upper())
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        rows = connection.execute(query, args).fetchall()
        return [serialize_market(connection, row) | {"source": "local"} for row in rows]


def get_local_market(market_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, symbol, name, question, description, status, tick_size, min_order_size,
                   market_type, resolved_outcome, resolved_at, created_at, updated_at
            FROM markets
            WHERE id = ?
            """,
            (market_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Market not found.")
        return serialize_market(connection, row) | {"source": "local"}


def get_public_market(market_id: int) -> dict[str, Any]:
    if settings.market_data_source == "polymarket":
        try:
            market = fetch_polymarket_market(market_id)
            if market:
                return market
        except Exception:
            pass
    return get_local_market(market_id)


def list_public_markets(status: str, limit: int) -> list[dict[str, Any]]:
    if settings.market_data_source == "polymarket":
        try:
            markets = fetch_polymarket_markets(limit)
            if markets:
                return markets
        except Exception:
            pass
    return list_local_markets(status, limit)


def empty_book() -> dict[str, Any]:
    return {"bids": [], "asks": [], "best_bid": None, "best_ask": None}


async def build_live_orderbook_payload(market_id: int) -> dict[str, Any]:
    try:
        market = get_public_market(market_id)
        return {
            "type": "orderbook",
            "market_id": market_id,
            "source": market.get("source", "local"),
            "question": market.get("question"),
            "outcomes": market.get("outcomes", {"YES": empty_book(), "NO": empty_book()}),
            "last_trade_price": market.get("last_trade_price"),
            "sent_at": utc_now(),
        }
    except HTTPException:
        with get_connection() as connection:
            yes_book = fetch_orderbook_for_outcome(connection, market_id, "YES")
            no_book = fetch_orderbook_for_outcome(connection, market_id, "NO")
        return {
            "type": "orderbook",
            "market_id": market_id,
            "source": "local",
            "outcomes": {"YES": yes_book, "NO": no_book},
            "sent_at": utc_now(),
        }


__all__ = [
    "build_live_orderbook_payload",
    "fetch_orderbook_for_outcome",
    "get_public_market",
    "list_public_markets",
    "safe_float",
]
