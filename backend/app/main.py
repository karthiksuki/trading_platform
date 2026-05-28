import json
import sqlite3
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="trading_platform_backend", version="0.1.0")
DB_PATH = "trading.db"
DB_LOCK = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                market_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                market_id INTEGER NOT NULL,
                type TEXT NOT NULL DEFAULT 'standard',
                quantity REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, market_id, type)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                user_id TEXT NOT NULL,
                market_id INTEGER,
                order_id INTEGER,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                asset TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                reference TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                asset TEXT NOT NULL,
                available REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, asset)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                endpoint TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    init_users_table()


class OrderRequest(BaseModel):
    user_id: str
    market_id: int
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)


class LimitOrderRequest(OrderRequest):
    side: Literal["BUY", "SELL"]


class MergeRequest(BaseModel):
    user_id: str
    source_market_id: int
    target_market_id: int
    quantity: float = Field(gt=0)


class SplitRequest(BaseModel):
    user_id: str
    market_id: int
    source_type: str
    left_type: str
    right_type: str
    ratio_left: float = Field(gt=0)
    ratio_right: float = Field(gt=0)
    quantity: float = Field(gt=0)


class PaymentRequest(BaseModel):
    user_id: str
    asset: str = Field(min_length=2, max_length=10)
    amount: float = Field(gt=0)
    reference: str | None = None


class OnboardingRequest(BaseModel):
    user_id: str
    wallet_address: str
    user_name: str = Field(min_length=2, max_length=80)
    user_profile: str = Field(default="", max_length=500)


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


def run_with_retry(operation: Any) -> Any:
    attempts = 3
    for attempt in range(attempts):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            # Handles sqlite lock contention to reduce deadlock-like failures.
            if "locked" in str(exc).lower() and attempt < attempts - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise


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


def init_users_table() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                wallet_address TEXT UNIQUE NOT NULL,
                user_name TEXT NOT NULL,
                user_profile TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


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


@app.post("/api/trading/buy")
def buy(payload: OrderRequest) -> dict[str, float | int | str]:
    with DB_LOCK, get_connection() as connection:
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, side, order_type, quantity, price, status, created_at)
            VALUES (?, ?, 'BUY', 'MARKET', ?, ?, 'FILLED', ?)
            """,
            (payload.user_id, payload.market_id, payload.quantity, payload.price, now),
        )
        order_id = int(cursor.lastrowid)
        current_qty = get_position_quantity(connection, payload.user_id, payload.market_id)
        upsert_position(connection, payload.user_id, payload.market_id, "standard", current_qty + payload.quantity)
        log_history(
            connection,
            "BUY",
            payload.user_id,
            payload.market_id,
            f"Bought {payload.quantity} @ {payload.price}",
            order_id,
        )
        connection.commit()
    return {"status": "filled", "order_id": order_id}


@app.post("/api/trading/sell")
def sell(payload: OrderRequest) -> dict[str, float | int | str]:
    with DB_LOCK, get_connection() as connection:
        current_qty = get_position_quantity(connection, payload.user_id, payload.market_id)
        if current_qty < payload.quantity:
            raise HTTPException(status_code=400, detail="Insufficient position quantity to sell.")
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, side, order_type, quantity, price, status, created_at)
            VALUES (?, ?, 'SELL', 'MARKET', ?, ?, 'FILLED', ?)
            """,
            (payload.user_id, payload.market_id, payload.quantity, payload.price, now),
        )
        order_id = int(cursor.lastrowid)
        upsert_position(connection, payload.user_id, payload.market_id, "standard", current_qty - payload.quantity)
        log_history(
            connection,
            "SELL",
            payload.user_id,
            payload.market_id,
            f"Sold {payload.quantity} @ {payload.price}",
            order_id,
        )
        connection.commit()
    return {"status": "filled", "order_id": order_id}


@app.post("/api/trading/limit")
def limit_order(payload: LimitOrderRequest) -> dict[str, int | str]:
    with DB_LOCK, get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, side, order_type, quantity, price, status, created_at)
            VALUES (?, ?, ?, 'LIMIT', ?, ?, 'PENDING', ?)
            """,
            (payload.user_id, payload.market_id, payload.side, payload.quantity, payload.price, utc_now()),
        )
        order_id = int(cursor.lastrowid)
        log_history(
            connection,
            "LIMIT",
            payload.user_id,
            payload.market_id,
            f"Placed {payload.side} limit {payload.quantity} @ {payload.price}",
            order_id,
        )
        connection.commit()
    return {"status": "pending", "order_id": order_id}


@app.post("/api/trading/merge")
def merge(payload: MergeRequest) -> dict[str, str]:
    with DB_LOCK, get_connection() as connection:
        source_qty = get_position_quantity(connection, payload.user_id, payload.source_market_id)
        if source_qty < payload.quantity:
            raise HTTPException(status_code=400, detail="Not enough source quantity to merge.")
        target_qty = get_position_quantity(connection, payload.user_id, payload.target_market_id)
        upsert_position(
            connection, payload.user_id, payload.source_market_id, "standard", source_qty - payload.quantity
        )
        upsert_position(
            connection, payload.user_id, payload.target_market_id, "standard", target_qty + payload.quantity
        )
        log_history(
            connection,
            "MERGE",
            payload.user_id,
            payload.target_market_id,
            f"Merged {payload.quantity} from market {payload.source_market_id} into {payload.target_market_id}",
        )
        connection.commit()
    return {"status": "merged"}


@app.post("/api/trading/split")
def split(payload: SplitRequest) -> dict[str, str]:
    total_ratio = payload.ratio_left + payload.ratio_right
    with DB_LOCK, get_connection() as connection:
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


@app.get("/api/trading/history")
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


@app.get("/api/trading/orderbooks/{market_id}")
def orderbook(market_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        buy_rows = connection.execute(
            """
            SELECT price, SUM(quantity) as total_quantity
            FROM orders
            WHERE market_id = ? AND side = 'BUY' AND order_type = 'LIMIT' AND status = 'PENDING'
            GROUP BY price
            ORDER BY price DESC
            """,
            (market_id,),
        ).fetchall()
        sell_rows = connection.execute(
            """
            SELECT price, SUM(quantity) as total_quantity
            FROM orders
            WHERE market_id = ? AND side = 'SELL' AND order_type = 'LIMIT' AND status = 'PENDING'
            GROUP BY price
            ORDER BY price ASC
            """,
            (market_id,),
        ).fetchall()
    return {
        "market_id": market_id,
        "bids": [{"price": float(row["price"]), "quantity": float(row["total_quantity"])} for row in buy_rows],
        "asks": [{"price": float(row["price"]), "quantity": float(row["total_quantity"])} for row in sell_rows],
    }


@app.post("/api/payments/deposit")
def deposit(
    payload: PaymentRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            cached = fetch_cached_idempotent_response(connection, "/api/payments/deposit", idempotency_key)
            if cached:
                return cached
            current = get_cash_balance(connection, payload.user_id, payload.asset.upper())
            next_amount = current + payload.amount
            set_cash_balance(connection, payload.user_id, payload.asset.upper(), next_amount)
            cursor = connection.execute(
                """
                INSERT INTO payment_transactions (user_id, action, asset, amount, status, reference, created_at)
                VALUES (?, 'DEPOSIT', ?, ?, 'SUCCESS', ?, ?)
                """,
                (payload.user_id, payload.asset.upper(), payload.amount, payload.reference, utc_now()),
            )
            transaction_id = int(cursor.lastrowid)
            log_history(
                connection,
                "PAYMENT_DEPOSIT",
                payload.user_id,
                None,
                f"Deposited {payload.amount} {payload.asset.upper()}",
            )
            result = {"status": "success", "transaction_id": transaction_id, "balance": next_amount}
            save_idempotent_response(connection, "/api/payments/deposit", idempotency_key, result)
            connection.commit()
            return result

    return run_with_retry(operation)


@app.post("/api/payments/withdraw")
def withdraw(
    payload: PaymentRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            cached = fetch_cached_idempotent_response(connection, "/api/payments/withdraw", idempotency_key)
            if cached:
                return cached
            current = get_cash_balance(connection, payload.user_id, payload.asset.upper())
            if current < payload.amount:
                raise HTTPException(status_code=400, detail="Insufficient cash balance.")
            next_amount = current - payload.amount
            set_cash_balance(connection, payload.user_id, payload.asset.upper(), next_amount)
            cursor = connection.execute(
                """
                INSERT INTO payment_transactions (user_id, action, asset, amount, status, reference, created_at)
                VALUES (?, 'WITHDRAW', ?, ?, 'SUCCESS', ?, ?)
                """,
                (payload.user_id, payload.asset.upper(), payload.amount, payload.reference, utc_now()),
            )
            transaction_id = int(cursor.lastrowid)
            log_history(
                connection,
                "PAYMENT_WITHDRAW",
                payload.user_id,
                None,
                f"Withdrew {payload.amount} {payload.asset.upper()}",
            )
            result = {"status": "success", "transaction_id": transaction_id, "balance": next_amount}
            save_idempotent_response(connection, "/api/payments/withdraw", idempotency_key, result)
            connection.commit()
            return result

    return run_with_retry(operation)


@app.get("/api/payments/transactions")
def list_transactions(user_id: str, limit: int = 50) -> list[dict[str, str | int | float | None]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, action, asset, amount, status, reference, created_at
            FROM payment_transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/payments/balances/{user_id}")
def list_balances(user_id: str) -> list[dict[str, str | float]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT asset, available
            FROM cash_balances
            WHERE user_id = ?
            ORDER BY asset ASC
            """,
            (user_id,),
        ).fetchall()
    return [{"asset": row["asset"], "available": float(row["available"])} for row in rows]


@app.post("/api/users/onboard")
def onboard_user(payload: OnboardingRequest) -> dict[str, str]:
    with DB_LOCK, get_connection() as connection:
        now = utc_now()
        existing = connection.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (payload.user_id,),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE users
                SET wallet_address = ?, user_name = ?, user_profile = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (payload.wallet_address, payload.user_name, payload.user_profile, now, payload.user_id),
            )
            status = "updated"
        else:
            connection.execute(
                """
                INSERT INTO users (user_id, wallet_address, user_name, user_profile, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (payload.user_id, payload.wallet_address, payload.user_name, payload.user_profile, now, now),
            )
            status = "created"
        log_history(
            connection,
            "ONBOARDING",
            payload.user_id,
            None,
            f"Onboarding {status} for {payload.user_name}",
        )
        connection.commit()
    return {"status": status, "user_id": payload.user_id}


@app.get("/api/users/{user_id}")
def get_user(user_id: str) -> dict[str, str]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, wallet_address, user_name, user_profile, created_at, updated_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return dict(row)
