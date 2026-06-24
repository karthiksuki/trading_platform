from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.database import DB_LOCK, get_connection
from app.core.time import utc_now
from app.schemas import LimitOrderRequest, MergeRequest, OrderRequest, SplitRequest
from app.services.accounts import require_active_user
from app.services.markets import fetch_orderbook_for_outcome
from app.services.trading import (
    get_cash_balance,
    get_position_quantity,
    log_history,
    match_limit_orders,
    set_cash_balance,
    upsert_position,
)

router = APIRouter(prefix="/api/trading", tags=["trading"])


@router.post("/buy")
def buy(payload: OrderRequest) -> dict[str, float | int | str]:
    with DB_LOCK, get_connection() as connection:
        require_active_user(connection, payload.user_id)
        now = utc_now()
        notional = payload.quantity * payload.price
        cash = get_cash_balance(connection, payload.user_id, "USD")
        if cash < notional:
            raise HTTPException(status_code=400, detail="Insufficient USD balance for buy.")
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, outcome, side, order_type, quantity, price, status, created_at)
            VALUES (?, ?, ?, 'BUY', 'MARKET', ?, ?, 'FILLED', ?)
            """,
            (payload.user_id, payload.market_id, payload.outcome, payload.quantity, payload.price, now),
        )
        order_id = int(cursor.lastrowid)
        current_qty = get_position_quantity(connection, payload.user_id, payload.market_id, payload.outcome)
        upsert_position(connection, payload.user_id, payload.market_id, payload.outcome, current_qty + payload.quantity)
        set_cash_balance(connection, payload.user_id, "USD", cash - notional)
        log_history(
            connection,
            "BUY",
            payload.user_id,
            payload.market_id,
            f"Bought {payload.quantity} {payload.outcome} @ {payload.price}",
            order_id,
        )
        connection.commit()
    return {"status": "filled", "order_id": order_id}


@router.post("/sell")
def sell(payload: OrderRequest) -> dict[str, float | int | str]:
    with DB_LOCK, get_connection() as connection:
        require_active_user(connection, payload.user_id)
        current_qty = get_position_quantity(connection, payload.user_id, payload.market_id, payload.outcome)
        if current_qty < payload.quantity:
            raise HTTPException(status_code=400, detail="Insufficient position quantity to sell.")
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, outcome, side, order_type, quantity, price, status, created_at)
            VALUES (?, ?, ?, 'SELL', 'MARKET', ?, ?, 'FILLED', ?)
            """,
            (payload.user_id, payload.market_id, payload.outcome, payload.quantity, payload.price, now),
        )
        order_id = int(cursor.lastrowid)
        upsert_position(connection, payload.user_id, payload.market_id, payload.outcome, current_qty - payload.quantity)
        seller_cash = get_cash_balance(connection, payload.user_id, "USD")
        set_cash_balance(connection, payload.user_id, "USD", seller_cash + (payload.quantity * payload.price))
        log_history(
            connection,
            "SELL",
            payload.user_id,
            payload.market_id,
            f"Sold {payload.quantity} {payload.outcome} @ {payload.price}",
            order_id,
        )
        connection.commit()
    return {"status": "filled", "order_id": order_id}


@router.post("/limit")
def limit_order(payload: LimitOrderRequest) -> dict[str, int | str]:
    with DB_LOCK, get_connection() as connection:
        require_active_user(connection, payload.user_id)
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, outcome, side, order_type, quantity, price, status, created_at, filled_quantity)
            VALUES (?, ?, ?, ?, 'LIMIT', ?, ?, 'PENDING', ?, 0)
            """,
            (payload.user_id, payload.market_id, payload.outcome, payload.side, payload.quantity, payload.price, utc_now()),
        )
        order_id = int(cursor.lastrowid)
        log_history(
            connection,
            "LIMIT",
            payload.user_id,
            payload.market_id,
            f"Placed {payload.side} {payload.outcome} limit {payload.quantity} @ {payload.price}",
            order_id,
        )
        matches = match_limit_orders(connection, payload.market_id)
        row = connection.execute(
            "SELECT status, filled_quantity, quantity FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        status = str(row["status"]) if row else "PENDING"
        filled = float(row["filled_quantity"]) if row else 0.0
        requested = float(row["quantity"]) if row else payload.quantity
        connection.commit()
    return {
        "status": status.lower(),
        "order_id": order_id,
        "matched_trades": matches,
        "filled_quantity": filled,
        "remaining_quantity": max(requested - filled, 0.0),
    }


@router.post("/merge")
def merge(payload: MergeRequest) -> dict[str, str]:
    with DB_LOCK, get_connection() as connection:
        require_active_user(connection, payload.user_id)
        source_qty = get_position_quantity(connection, payload.user_id, payload.source_market_id, payload.source_outcome)
        if source_qty < payload.quantity:
            raise HTTPException(status_code=400, detail="Not enough source quantity to merge.")
        target_qty = get_position_quantity(connection, payload.user_id, payload.target_market_id, payload.target_outcome)
        upsert_position(
            connection, payload.user_id, payload.source_market_id, payload.source_outcome, source_qty - payload.quantity
        )
        upsert_position(
            connection, payload.user_id, payload.target_market_id, payload.target_outcome, target_qty + payload.quantity
        )
        log_history(
            connection,
            "MERGE",
            payload.user_id,
            payload.target_market_id,
            f"Merged {payload.quantity} {payload.source_outcome} from market {payload.source_market_id} into {payload.target_outcome} on market {payload.target_market_id}",
        )
        connection.commit()
    return {"status": "merged"}


@router.post("/split")
def split(payload: SplitRequest) -> dict[str, str]:
    total_ratio = payload.ratio_left + payload.ratio_right
    with DB_LOCK, get_connection() as connection:
        require_active_user(connection, payload.user_id)
        source_qty = get_position_quantity(connection, payload.user_id, payload.market_id, payload.source_type)
        if source_qty < payload.quantity:
            raise HTTPException(status_code=400, detail="Not enough quantity to split.")
        left_qty = payload.quantity * (payload.ratio_left / total_ratio)
        right_qty = payload.quantity * (payload.ratio_right / total_ratio)
        upsert_position(connection, payload.user_id, payload.market_id, payload.source_type, source_qty - payload.quantity)
        existing_left = get_position_quantity(connection, payload.user_id, payload.market_id, payload.left_type)
        existing_right = get_position_quantity(connection, payload.user_id, payload.market_id, payload.right_type)
        upsert_position(connection, payload.user_id, payload.market_id, payload.left_type, existing_left + left_qty)
        upsert_position(connection, payload.user_id, payload.market_id, payload.right_type, existing_right + right_qty)
        log_history(
            connection,
            "SPLIT",
            payload.user_id,
            payload.market_id,
            f"Split {payload.quantity} from {payload.source_type} into {payload.left_type}:{left_qty} and {payload.right_type}:{right_qty}",
        )
        connection.commit()
    return {"status": "split"}


@router.get("/history")
def history(user_id: str | None = None, market_id: int | None = None, limit: int = 50) -> list[dict[str, str | int | None]]:
    query = "SELECT id, action, user_id, market_id, order_id, details, created_at FROM history"
    conditions: list[str] = []
    args: list[str | int] = []
    if user_id:
        conditions.append("user_id = ?")
        args.append(user_id)
    if market_id is not None:
        conditions.append("market_id = ?")
        args.append(market_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, args).fetchall()
    return [dict(row) for row in rows]


@router.get("/open-orders")
def open_orders(user_id: str, market_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = """
        SELECT id, user_id, market_id, outcome, side, order_type, quantity, price, status, filled_quantity, created_at
        FROM orders
        WHERE user_id = ? AND status IN ('PENDING', 'PARTIAL')
    """
    args: list[str | int] = [user_id]
    if market_id is not None:
        query += " AND market_id = ?"
        args.append(market_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, args).fetchall()
    payload: list[dict[str, Any]] = []
    for row in rows:
        requested = float(row["quantity"])
        filled = float(row["filled_quantity"] or 0)
        payload.append(
            {
                "id": int(row["id"]),
                "user_id": str(row["user_id"]),
                "market_id": int(row["market_id"]),
                "outcome": str(row["outcome"]),
                "side": str(row["side"]),
                "order_type": str(row["order_type"]),
                "status": str(row["status"]),
                "price": float(row["price"]),
                "quantity": requested,
                "filled_quantity": filled,
                "remaining_quantity": max(requested - filled, 0.0),
                "created_at": str(row["created_at"]),
            }
        )
    return payload


@router.get("/orderbooks/{market_id}")
def orderbook(market_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        yes_book = fetch_orderbook_for_outcome(connection, market_id, "YES")
        no_book = fetch_orderbook_for_outcome(connection, market_id, "NO")
    return {
        "market_id": market_id,
        "outcomes": {"YES": yes_book, "NO": no_book},
        "bids": yes_book["bids"],
        "asks": yes_book["asks"],
    }


@router.get("/trades")
def list_trades(market_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = """
        SELECT t.id, t.market_id, t.buy_order_id, t.sell_order_id, t.quantity, t.execution_price, t.created_at,
               o.outcome
        FROM trades t
        JOIN orders o ON o.id = t.buy_order_id
    """
    args: list[int] = []
    if market_id is not None:
        query += " WHERE t.market_id = ?"
        args.append(market_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_connection() as connection:
        rows = connection.execute(query, args).fetchall()
    return [
        {
            "id": int(row["id"]),
            "market_id": int(row["market_id"]),
            "buy_order_id": int(row["buy_order_id"]),
            "sell_order_id": int(row["sell_order_id"]),
            "outcome": str(row["outcome"]),
            "quantity": float(row["quantity"]),
            "execution_price": float(row["execution_price"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
