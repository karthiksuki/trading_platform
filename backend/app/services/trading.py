import json
import sqlite3
import time
from typing import Any

from fastapi import HTTPException

from app.core.time import utc_now
from app.schemas import PaymentRequest
from app.services.accounts import require_active_user


def log_history(
    connection: sqlite3.Connection,
    action: str,
    user_id: str,
    market_id: int | None,
    details: str,
    order_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO history (action, user_id, market_id, order_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (action, user_id, market_id, order_id, details, utc_now()),
    )


def fetch_cached_idempotent_response(connection: sqlite3.Connection, endpoint: str, key: str | None) -> dict[str, Any] | None:
    if not key:
        return None
    row = connection.execute(
        "SELECT response_json FROM idempotency_keys WHERE endpoint = ? AND key = ?",
        (endpoint, key),
    ).fetchone()
    if not row:
        return None
    return json.loads(row["response_json"])


def save_idempotent_response(connection: sqlite3.Connection, endpoint: str, key: str | None, payload: dict[str, Any]) -> None:
    if not key:
        return
    connection.execute(
        """
        INSERT OR REPLACE INTO idempotency_keys (key, endpoint, response_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (key, endpoint, json.dumps(payload), utc_now()),
    )


def coerce_payment_payload(payload: Any) -> PaymentRequest:
    if isinstance(payload, PaymentRequest):
        return payload
    if isinstance(payload, str):
        try:
            return PaymentRequest.model_validate_json(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid payment payload format.") from exc
    if isinstance(payload, dict):
        try:
            return PaymentRequest.model_validate(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid payment payload data.") from exc
    raise HTTPException(status_code=400, detail="Payment payload must be a JSON object.")


def run_with_retry(operation: Any) -> Any:
    attempts = 3
    for attempt in range(attempts):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < attempts - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
    raise RuntimeError("Unreachable retry state.")


def get_cash_balance(connection: sqlite3.Connection, user_id: str, asset: str) -> float:
    row = connection.execute(
        "SELECT available FROM cash_balances WHERE user_id = ? AND asset = ?",
        (user_id, asset),
    ).fetchone()
    return float(row["available"]) if row else 0.0


def set_cash_balance(connection: sqlite3.Connection, user_id: str, asset: str, amount: float) -> None:
    now = utc_now()
    row = connection.execute(
        "SELECT id FROM cash_balances WHERE user_id = ? AND asset = ?",
        (user_id, asset),
    ).fetchone()
    if row:
        connection.execute(
            "UPDATE cash_balances SET available = ?, updated_at = ? WHERE id = ?",
            (amount, now, row["id"]),
        )
    else:
        connection.execute(
            """
            INSERT INTO cash_balances (user_id, asset, available, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, asset, amount, now),
        )


def order_remaining_quantity(order_row: sqlite3.Row) -> float:
    filled_quantity = float(order_row["filled_quantity"]) if "filled_quantity" in order_row.keys() else 0.0
    return max(float(order_row["quantity"]) - filled_quantity, 0.0)


def persist_order_fill(connection: sqlite3.Connection, order_id: int, newly_filled: float) -> tuple[float, str]:
    row = connection.execute(
        "SELECT quantity, filled_quantity FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found while matching.")
    total = float(row["quantity"])
    current_filled = float(row["filled_quantity"] or 0)
    next_filled = min(total, current_filled + newly_filled)
    next_status = "FILLED" if next_filled >= total else "PARTIAL"
    connection.execute(
        "UPDATE orders SET filled_quantity = ?, status = ? WHERE id = ?",
        (next_filled, next_status, order_id),
    )
    return next_filled, next_status


def get_position_quantity(
    connection: sqlite3.Connection,
    user_id: str,
    market_id: int,
    position_type: str = "standard",
) -> float:
    row = connection.execute(
        """
        SELECT quantity FROM positions
        WHERE user_id = ? AND market_id = ? AND type = ?
        """,
        (user_id, market_id, position_type),
    ).fetchone()
    return float(row["quantity"]) if row else 0.0


def upsert_position(
    connection: sqlite3.Connection,
    user_id: str,
    market_id: int,
    position_type: str,
    quantity: float,
) -> None:
    now = utc_now()
    existing = connection.execute(
        """
        SELECT id FROM positions
        WHERE user_id = ? AND market_id = ? AND type = ?
        """,
        (user_id, market_id, position_type),
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE positions
            SET quantity = ?, updated_at = ?
            WHERE id = ?
            """,
            (quantity, now, existing["id"]),
        )
    else:
        connection.execute(
            """
            INSERT INTO positions (user_id, market_id, type, quantity, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, market_id, position_type, quantity, now, now),
        )


def execute_match(
    connection: sqlite3.Connection,
    market_id: int,
    buy_order: sqlite3.Row,
    sell_order: sqlite3.Row,
    quantity: float,
    execution_price: float,
) -> None:
    buy_user = str(buy_order["user_id"])
    sell_user = str(sell_order["user_id"])
    if buy_user == sell_user:
        return

    require_active_user(connection, buy_user)
    require_active_user(connection, sell_user)

    gross_cost = quantity * execution_price
    buyer_cash = get_cash_balance(connection, buy_user, "USD")
    if buyer_cash < gross_cost:
        connection.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (int(buy_order["id"]),))
        log_history(
            connection,
            "LIMIT",
            buy_user,
            market_id,
            "Buy limit order cancelled by matcher: insufficient USD balance.",
            int(buy_order["id"]),
        )
        return

    outcome = str(buy_order["outcome"])
    seller_position = get_position_quantity(connection, sell_user, market_id, outcome)
    if seller_position < quantity:
        connection.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (int(sell_order["id"]),))
        log_history(
            connection,
            "LIMIT",
            sell_user,
            market_id,
            "Sell limit order cancelled by matcher: insufficient position quantity.",
            int(sell_order["id"]),
        )
        return

    buyer_position = get_position_quantity(connection, buy_user, market_id, outcome)
    upsert_position(connection, buy_user, market_id, outcome, buyer_position + quantity)
    upsert_position(connection, sell_user, market_id, outcome, seller_position - quantity)
    set_cash_balance(connection, buy_user, "USD", buyer_cash - gross_cost)
    seller_cash = get_cash_balance(connection, sell_user, "USD")
    set_cash_balance(connection, sell_user, "USD", seller_cash + gross_cost)

    buy_filled, buy_status = persist_order_fill(connection, int(buy_order["id"]), quantity)
    sell_filled, sell_status = persist_order_fill(connection, int(sell_order["id"]), quantity)
    cursor = connection.execute(
        """
        INSERT INTO trades (market_id, buy_order_id, sell_order_id, quantity, execution_price, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (market_id, int(buy_order["id"]), int(sell_order["id"]), quantity, execution_price, utc_now()),
    )
    trade_id = int(cursor.lastrowid)
    log_history(
        connection,
        "BUY",
        buy_user,
        market_id,
        f"Trade fill #{trade_id}: bought {quantity} {outcome} @ {execution_price}. filled={buy_filled} status={buy_status}",
        int(buy_order["id"]),
    )
    log_history(
        connection,
        "SELL",
        sell_user,
        market_id,
        f"Trade fill #{trade_id}: sold {quantity} {outcome} @ {execution_price}. filled={sell_filled} status={sell_status}",
        int(sell_order["id"]),
    )


def match_limit_orders(connection: sqlite3.Connection, market_id: int) -> int:
    total_matches = 0
    for outcome in ("YES", "NO"):
        while True:
            buy = connection.execute(
                """
                SELECT id, user_id, outcome, quantity, filled_quantity, price, created_at
                FROM orders
                WHERE market_id = ?
                  AND outcome = ?
                  AND side = 'BUY'
                  AND order_type = 'LIMIT'
                  AND status IN ('PENDING', 'PARTIAL')
                ORDER BY price DESC, created_at ASC
                LIMIT 1
                """,
                (market_id, outcome),
            ).fetchone()
            sell = connection.execute(
                """
                SELECT id, user_id, outcome, quantity, filled_quantity, price, created_at
                FROM orders
                WHERE market_id = ?
                  AND outcome = ?
                  AND side = 'SELL'
                  AND order_type = 'LIMIT'
                  AND status IN ('PENDING', 'PARTIAL')
                ORDER BY price ASC, created_at ASC
                LIMIT 1
                """,
                (market_id, outcome),
            ).fetchone()
            if not buy or not sell:
                break

            if float(buy["price"]) < float(sell["price"]):
                break

            buy_remaining = order_remaining_quantity(buy)
            sell_remaining = order_remaining_quantity(sell)
            quantity = min(buy_remaining, sell_remaining)
            if quantity <= 0:
                if buy_remaining <= 0:
                    connection.execute("UPDATE orders SET status = 'FILLED' WHERE id = ?", (int(buy["id"]),))
                if sell_remaining <= 0:
                    connection.execute("UPDATE orders SET status = 'FILLED' WHERE id = ?", (int(sell["id"]),))
                continue

            execute_match(connection, market_id, buy, sell, quantity, float(sell["price"]))
            total_matches += 1
    return total_matches
