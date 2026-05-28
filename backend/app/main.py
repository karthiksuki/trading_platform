import json
import sqlite3
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from fastapi import Body, FastAPI, Header, HTTPException
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
    init_admin_emails_table()
    init_trades_table()
    init_markets_table()


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
    profile_picture: str | None = None


class AdminAdjustBalanceRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    asset: str = Field(min_length=2, max_length=20)
    delta: float
    reason: str = Field(min_length=3, max_length=200)


class AdminFreezeRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    freeze: bool
    reason: str = Field(min_length=3, max_length=200)


class AdminSetRoleRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    is_admin: bool


class AdminAccessGrantRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class AdminAuthenticatedRequest(BaseModel):
    admin_email: str = Field(min_length=5, max_length=200)
    admin_password: str = Field(min_length=1, max_length=200)


class AdminCreateMarketRequest(AdminAuthenticatedRequest):
    symbol: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=120)
    tick_size: float = Field(gt=0)
    min_order_size: float = Field(gt=0)


class AdminMarketStatusRequest(AdminAuthenticatedRequest):
    status: Literal["OPEN", "PAUSED", "CLOSED"]


class AdminStaleCleanupRequest(AdminAuthenticatedRequest):
    max_age_minutes: int = Field(gt=0, le=10080)
    market_id: int | None = None


class AdminReconcileRequest(AdminAuthenticatedRequest):
    market_id: int | None = None


class AdminRiskRecalcRequest(AdminAuthenticatedRequest):
    limit: int = Field(default=20, gt=0, le=100)


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
                profile_picture TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()]
        if "profile_picture" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
        if "is_admin" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "is_frozen" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN is_frozen INTEGER NOT NULL DEFAULT 0")
        connection.commit()


def init_admin_emails_table() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = [row["name"] for row in connection.execute("PRAGMA table_info(admin_emails)").fetchall()]
        if "password" not in columns:
            connection.execute("ALTER TABLE admin_emails ADD COLUMN password TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            INSERT INTO admin_emails (email, password, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET password = excluded.password
            """,
            ("karcode95@gmail.com", "testin@test", utc_now()),
        )
        connection.commit()


def init_trades_table() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id INTEGER NOT NULL,
                buy_order_id INTEGER NOT NULL,
                sell_order_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                execution_price REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        order_columns = [row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()]
        if "filled_quantity" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN filled_quantity REAL NOT NULL DEFAULT 0")
        connection.commit()


def init_markets_table() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS markets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                tick_size REAL NOT NULL,
                min_order_size REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def require_active_user(connection: sqlite3.Connection, user_id: str) -> None:
    row = connection.execute(
        "SELECT user_id, is_frozen FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row and int(row["is_frozen"]) == 1:
        raise HTTPException(status_code=403, detail="Account is frozen by admin.")


def require_admin(connection: sqlite3.Connection, user_id: str) -> None:
    row = connection.execute(
        "SELECT user_id, is_admin FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row or int(row["is_admin"]) != 1:
        raise HTTPException(status_code=403, detail="Admin access required.")


def require_admin_credentials(connection: sqlite3.Connection, admin_email: str, admin_password: str) -> str:
    normalized_email = admin_email.strip().lower()
    normalized_password = admin_password.strip()
    if not normalized_email or not normalized_password:
        raise HTTPException(status_code=401, detail="Admin credentials are required.")
    row = connection.execute(
        "SELECT email FROM admin_emails WHERE lower(email) = ? AND password = ?",
        (normalized_email, normalized_password),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid admin credentials.")
    return normalized_email


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

    seller_position = get_position_quantity(connection, sell_user, market_id)
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

    buyer_position = get_position_quantity(connection, buy_user, market_id)
    upsert_position(connection, buy_user, market_id, "standard", buyer_position + quantity)
    upsert_position(connection, sell_user, market_id, "standard", seller_position - quantity)
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
        f"Trade fill #{trade_id}: bought {quantity} @ {execution_price}. filled={buy_filled} status={buy_status}",
        int(buy_order["id"]),
    )
    log_history(
        connection,
        "SELL",
        sell_user,
        market_id,
        f"Trade fill #{trade_id}: sold {quantity} @ {execution_price}. filled={sell_filled} status={sell_status}",
        int(sell_order["id"]),
    )


def match_limit_orders(connection: sqlite3.Connection, market_id: int) -> int:
    total_matches = 0
    while True:
        buy = connection.execute(
            """
            SELECT id, user_id, quantity, filled_quantity, price, created_at
            FROM orders
            WHERE market_id = ? AND side = 'BUY' AND order_type = 'LIMIT' AND status IN ('PENDING', 'PARTIAL')
            ORDER BY price DESC, created_at ASC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        sell = connection.execute(
            """
            SELECT id, user_id, quantity, filled_quantity, price, created_at
            FROM orders
            WHERE market_id = ? AND side = 'SELL' AND order_type = 'LIMIT' AND status IN ('PENDING', 'PARTIAL')
            ORDER BY price ASC, created_at ASC
            LIMIT 1
            """,
            (market_id,),
        ).fetchone()
        if not buy or not sell:
            break

        buy_price = float(buy["price"])
        sell_price = float(sell["price"])
        if buy_price < sell_price:
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

        execution_price = float(sell["price"])
        execute_match(connection, market_id, buy, sell, quantity, execution_price)
        total_matches += 1
    return total_matches


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
        require_active_user(connection, payload.user_id)
        now = utc_now()
        notional = payload.quantity * payload.price
        cash = get_cash_balance(connection, payload.user_id, "USD")
        if cash < notional:
            raise HTTPException(status_code=400, detail="Insufficient USD balance for buy.")
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
        set_cash_balance(connection, payload.user_id, "USD", cash - notional)
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
        require_active_user(connection, payload.user_id)
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
        seller_cash = get_cash_balance(connection, payload.user_id, "USD")
        set_cash_balance(connection, payload.user_id, "USD", seller_cash + (payload.quantity * payload.price))
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
        require_active_user(connection, payload.user_id)
        cursor = connection.execute(
            """
            INSERT INTO orders (user_id, market_id, side, order_type, quantity, price, status, created_at, filled_quantity)
            VALUES (?, ?, ?, 'LIMIT', ?, ?, 'PENDING', ?, 0)
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


@app.get("/api/trading/open-orders")
def open_orders(user_id: str, market_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = """
        SELECT id, user_id, market_id, side, order_type, quantity, price, status, filled_quantity, created_at
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


@app.get("/api/trading/orderbooks/{market_id}")
def orderbook(market_id: int) -> dict[str, Any]:
    with get_connection() as connection:
        buy_rows = connection.execute(
            """
            SELECT price, SUM(quantity - COALESCE(filled_quantity, 0)) as total_quantity
            FROM orders
            WHERE market_id = ? AND side = 'BUY' AND order_type = 'LIMIT' AND status IN ('PENDING', 'PARTIAL')
            GROUP BY price
            ORDER BY price DESC
            """,
            (market_id,),
        ).fetchall()
        sell_rows = connection.execute(
            """
            SELECT price, SUM(quantity - COALESCE(filled_quantity, 0)) as total_quantity
            FROM orders
            WHERE market_id = ? AND side = 'SELL' AND order_type = 'LIMIT' AND status IN ('PENDING', 'PARTIAL')
            GROUP BY price
            ORDER BY price ASC
            """,
            (market_id,),
        ).fetchall()
    return {
        "market_id": market_id,
        "bids": [
            {"price": float(row["price"]), "quantity": float(row["total_quantity"])}
            for row in buy_rows
            if float(row["total_quantity"]) > 0
        ],
        "asks": [
            {"price": float(row["price"]), "quantity": float(row["total_quantity"])}
            for row in sell_rows
            if float(row["total_quantity"]) > 0
        ],
    }


@app.get("/api/trading/trades")
def list_trades(market_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = """
        SELECT id, market_id, buy_order_id, sell_order_id, quantity, execution_price, created_at
        FROM trades
    """
    args: list[int] = []
    if market_id is not None:
        query += " WHERE market_id = ?"
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
            "quantity": float(row["quantity"]),
            "execution_price": float(row["execution_price"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


@app.post("/api/payments/deposit")
def deposit(
    payload: Any = Body(...), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    payment = coerce_payment_payload(payload)

    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            cached = fetch_cached_idempotent_response(connection, "/api/payments/deposit", idempotency_key)
            if cached:
                return cached
            current = get_cash_balance(connection, payment.user_id, payment.asset.upper())
            next_amount = current + payment.amount
            set_cash_balance(connection, payment.user_id, payment.asset.upper(), next_amount)
            cursor = connection.execute(
                """
                INSERT INTO payment_transactions (user_id, action, asset, amount, status, reference, created_at)
                VALUES (?, 'DEPOSIT', ?, ?, 'SUCCESS', ?, ?)
                """,
                (payment.user_id, payment.asset.upper(), payment.amount, payment.reference, utc_now()),
            )
            transaction_id = int(cursor.lastrowid)
            log_history(
                connection,
                "PAYMENT_DEPOSIT",
                payment.user_id,
                None,
                f"Deposited {payment.amount} {payment.asset.upper()}",
            )
            result = {"status": "success", "transaction_id": transaction_id, "balance": next_amount}
            save_idempotent_response(connection, "/api/payments/deposit", idempotency_key, result)
            connection.commit()
            return result

    return run_with_retry(operation)


@app.post("/api/payments/withdraw")
def withdraw(
    payload: Any = Body(...), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    payment = coerce_payment_payload(payload)

    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            cached = fetch_cached_idempotent_response(connection, "/api/payments/withdraw", idempotency_key)
            if cached:
                return cached
            current = get_cash_balance(connection, payment.user_id, payment.asset.upper())
            if current < payment.amount:
                raise HTTPException(status_code=400, detail="Insufficient cash balance.")
            next_amount = current - payment.amount
            set_cash_balance(connection, payment.user_id, payment.asset.upper(), next_amount)
            cursor = connection.execute(
                """
                INSERT INTO payment_transactions (user_id, action, asset, amount, status, reference, created_at)
                VALUES (?, 'WITHDRAW', ?, ?, 'SUCCESS', ?, ?)
                """,
                (payment.user_id, payment.asset.upper(), payment.amount, payment.reference, utc_now()),
            )
            transaction_id = int(cursor.lastrowid)
            log_history(
                connection,
                "PAYMENT_WITHDRAW",
                payment.user_id,
                None,
                f"Withdrew {payment.amount} {payment.asset.upper()}",
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
            # Keep onboarding single-use per account to avoid duplicate onboarding history noise.
            return {"status": "exists", "user_id": payload.user_id}
        else:
            connection.execute(
                """
                INSERT INTO users (
                    user_id, wallet_address, user_name, user_profile, profile_picture, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.user_id,
                    payload.wallet_address,
                    payload.user_name,
                    payload.user_profile,
                    payload.profile_picture,
                    now,
                    now,
                ),
            )
            status = "created"
        log_history(connection, "ONBOARDING", payload.user_id, None, f"Onboarding {status} for {payload.user_name}")
        connection.commit()
    return {"status": status, "user_id": payload.user_id}


@app.get("/api/users/{user_id}")
def get_user(user_id: str) -> dict[str, str]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, wallet_address, user_name, user_profile, profile_picture, is_admin, is_frozen, created_at, updated_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return dict(row)


@app.post("/api/admin/access_grant")
def admin_access_grant(payload: AdminAccessGrantRequest) -> dict[str, str | bool]:
    normalized_email = payload.email.strip().lower()
    normalized_password = payload.password.strip()
    if not normalized_email or not normalized_password:
        return {"access": "nope", "granted": False}
    with DB_LOCK, get_connection() as connection:
        row = connection.execute(
            "SELECT email FROM admin_emails WHERE lower(email) = ? AND password = ?",
            (normalized_email, normalized_password),
        ).fetchone()
    if row:
        return {"access": "grant", "granted": True}
    return {"access": "nope", "granted": False}


@app.post("/api/admin/markets")
def admin_create_market(payload: AdminCreateMarketRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO markets (symbol, name, status, tick_size, min_order_size, created_at, updated_at)
            VALUES (?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            (payload.symbol.upper(), payload.name, payload.tick_size, payload.min_order_size, now, now),
        )
        market_id = int(cursor.lastrowid)
        log_history(
            connection,
            "ADMIN_MARKET_CREATE",
            admin_email,
            market_id,
            f"Created market {payload.symbol.upper()} ({payload.name})",
        )
        connection.commit()
    return {"status": "created", "market_id": market_id}


@app.get("/api/admin/markets")
def admin_list_markets(admin_email: str, admin_password: str) -> list[dict[str, Any]]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        rows = connection.execute(
            """
            SELECT id, symbol, name, status, tick_size, min_order_size, created_at, updated_at
            FROM markets
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/markets/{market_id}/status")
def admin_set_market_status(market_id: int, payload: AdminMarketStatusRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        row = connection.execute("SELECT id FROM markets WHERE id = ?", (market_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Market not found.")
        connection.execute(
            "UPDATE markets SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status, utc_now(), market_id),
        )
        log_history(
            connection,
            "ADMIN_MARKET_STATUS",
            admin_email,
            market_id,
            f"Updated market {market_id} status to {payload.status}",
        )
        connection.commit()
    return {"status": "ok", "market_id": market_id, "market_status": payload.status}


@app.get("/api/admin/monitoring/summary")
def admin_monitoring_summary(admin_email: str, admin_password: str) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        open_orders = connection.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status IN ('PENDING', 'PARTIAL')"
        ).fetchone()
        frozen_users = connection.execute("SELECT COUNT(*) AS count FROM users WHERE is_frozen = 1").fetchone()
        markets_total = connection.execute("SELECT COUNT(*) AS count FROM markets").fetchone()
        markets_open = connection.execute("SELECT COUNT(*) AS count FROM markets WHERE status = 'OPEN'").fetchone()
        trades_1h = connection.execute(
            "SELECT COUNT(*) AS count FROM trades WHERE datetime(created_at) >= datetime('now', '-1 hour')"
        ).fetchone()
        trades_24h = connection.execute(
            "SELECT COUNT(*) AS count FROM trades WHERE datetime(created_at) >= datetime('now', '-24 hour')"
        ).fetchone()
        recent_failures = connection.execute(
            """
            SELECT COUNT(*) AS count FROM history
            WHERE datetime(created_at) >= datetime('now', '-24 hour')
              AND (lower(action) LIKE '%fail%' OR lower(details) LIKE '%fail%' OR lower(details) LIKE '%insufficient%')
            """
        ).fetchone()
    return {
        "open_orders": int(open_orders["count"]) if open_orders else 0,
        "frozen_users": int(frozen_users["count"]) if frozen_users else 0,
        "markets_total": int(markets_total["count"]) if markets_total else 0,
        "markets_open": int(markets_open["count"]) if markets_open else 0,
        "trades_1h": int(trades_1h["count"]) if trades_1h else 0,
        "trades_24h": int(trades_24h["count"]) if trades_24h else 0,
        "recent_failures": int(recent_failures["count"]) if recent_failures else 0,
    }


@app.get("/api/admin/monitoring/logs")
def admin_monitoring_logs(
    admin_email: str,
    admin_password: str,
    action: str | None = None,
    market_id: int | None = None,
    user_id: str | None = None,
    since: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        query = "SELECT id, action, user_id, market_id, order_id, details, created_at FROM history"
        args: list[Any] = []
        filters: list[str] = []
        if action:
            filters.append("action = ?")
            args.append(action)
        if market_id is not None:
            filters.append("market_id = ?")
            args.append(market_id)
        if user_id:
            filters.append("user_id = ?")
            args.append(user_id)
        if since:
            filters.append("created_at >= ?")
            args.append(since)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        rows = connection.execute(query, args).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/admin/monitoring/market-health")
def admin_market_health(admin_email: str, admin_password: str) -> list[dict[str, Any]]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        markets = connection.execute(
            "SELECT id, symbol, name, status FROM markets ORDER BY id DESC"
        ).fetchall()
        payload: list[dict[str, Any]] = []
        for market in markets:
            top_bid = connection.execute(
                """
                SELECT MAX(price) AS best_bid
                FROM orders
                WHERE market_id = ? AND side = 'BUY' AND status IN ('PENDING', 'PARTIAL')
                """,
                (int(market["id"]),),
            ).fetchone()
            top_ask = connection.execute(
                """
                SELECT MIN(price) AS best_ask
                FROM orders
                WHERE market_id = ? AND side = 'SELL' AND status IN ('PENDING', 'PARTIAL')
                """,
                (int(market["id"]),),
            ).fetchone()
            last_trade = connection.execute(
                """
                SELECT created_at, execution_price
                FROM trades
                WHERE market_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (int(market["id"]),),
            ).fetchone()
            bid = float(top_bid["best_bid"]) if top_bid and top_bid["best_bid"] is not None else None
            ask = float(top_ask["best_ask"]) if top_ask and top_ask["best_ask"] is not None else None
            spread = (ask - bid) if bid is not None and ask is not None else None
            payload.append(
                {
                    "market_id": int(market["id"]),
                    "symbol": str(market["symbol"]),
                    "name": str(market["name"]),
                    "status": str(market["status"]),
                    "best_bid": bid,
                    "best_ask": ask,
                    "spread": spread,
                    "last_trade_at": str(last_trade["created_at"]) if last_trade else None,
                    "last_trade_price": float(last_trade["execution_price"]) if last_trade else None,
                }
            )
    return payload


@app.post("/api/admin/ops/stale-order-cleanup")
def admin_stale_order_cleanup(payload: AdminStaleCleanupRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        query = """
            SELECT id, market_id
            FROM orders
            WHERE status IN ('PENDING', 'PARTIAL')
              AND datetime(created_at) <= datetime('now', ?)
        """
        args: list[Any] = [f"-{payload.max_age_minutes} minute"]
        if payload.market_id is not None:
            query += " AND market_id = ?"
            args.append(payload.market_id)
        stale_orders = connection.execute(query, args).fetchall()
        ids = [int(row["id"]) for row in stale_orders]
        for stale in stale_orders:
            connection.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?", (int(stale["id"]),))
            log_history(
                connection,
                "ADMIN_STALE_CLEANUP",
                admin_email,
                int(stale["market_id"]),
                f"Cancelled stale order {int(stale['id'])}",
                int(stale["id"]),
            )
        connection.commit()
    return {"status": "ok", "cancelled_orders": len(ids), "order_ids": ids}


@app.post("/api/admin/ops/reconcile")
def admin_reconcile(payload: AdminReconcileRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        query = """
            SELECT p.user_id, p.market_id, p.quantity AS position_qty,
                   COALESCE(bq.buy_qty, 0) - COALESCE(sq.sell_qty, 0) AS trade_net_qty
            FROM positions p
            LEFT JOIN (
                SELECT o.user_id, t.market_id, SUM(t.quantity) AS buy_qty
                FROM trades t
                JOIN orders o ON o.id = t.buy_order_id
                GROUP BY o.user_id, t.market_id
            ) bq ON bq.user_id = p.user_id AND bq.market_id = p.market_id
            LEFT JOIN (
                SELECT o.user_id, t.market_id, SUM(t.quantity) AS sell_qty
                FROM trades t
                JOIN orders o ON o.id = t.sell_order_id
                GROUP BY o.user_id, t.market_id
            ) sq ON sq.user_id = p.user_id AND sq.market_id = p.market_id
        """
        args: list[Any] = []
        if payload.market_id is not None:
            query += " WHERE p.market_id = ?"
            args.append(payload.market_id)
        rows = connection.execute(query, args).fetchall()
        mismatches: list[dict[str, Any]] = []
        for row in rows:
            position_qty = float(row["position_qty"])
            trade_net = float(row["trade_net_qty"])
            delta = position_qty - trade_net
            if abs(delta) > 0.0001:
                mismatches.append(
                    {
                        "user_id": str(row["user_id"]),
                        "market_id": int(row["market_id"]),
                        "position_qty": position_qty,
                        "trade_net_qty": trade_net,
                        "delta": delta,
                    }
                )
        log_history(
            connection,
            "ADMIN_RECONCILE",
            admin_email,
            payload.market_id,
            f"Reconciliation complete. mismatches={len(mismatches)}",
        )
        connection.commit()
    return {"status": "ok", "checked_rows": len(rows), "mismatches": mismatches}


@app.post("/api/admin/ops/risk-recalc")
def admin_risk_recalc(payload: AdminRiskRecalcRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        positions = connection.execute(
            """
            SELECT p.user_id, p.market_id, p.quantity,
                   (
                       SELECT t.execution_price
                       FROM trades t
                       WHERE t.market_id = p.market_id
                       ORDER BY t.created_at DESC
                       LIMIT 1
                   ) AS mark_price
            FROM positions p
            """
        ).fetchall()
        exposure_by_user: dict[str, float] = {}
        for row in positions:
            user = str(row["user_id"])
            quantity = float(row["quantity"])
            mark_price = float(row["mark_price"]) if row["mark_price"] is not None else 0.0
            exposure_by_user[user] = exposure_by_user.get(user, 0.0) + abs(quantity * mark_price)
        ranked = sorted(exposure_by_user.items(), key=lambda item: item[1], reverse=True)
        top = [{"user_id": user, "exposure": exposure} for user, exposure in ranked[: payload.limit]]
        log_history(
            connection,
            "ADMIN_RISK_RECALC",
            admin_email,
            None,
            f"Risk recalculation complete for {len(exposure_by_user)} users",
        )
        connection.commit()
    return {"status": "ok", "users_evaluated": len(exposure_by_user), "top_exposures": top}


@app.get("/api/admin/overview")
def admin_overview(admin_user_id: str) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        require_admin(connection, admin_user_id)
        user_count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        open_orders_count = connection.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status IN ('PENDING', 'PARTIAL')"
        ).fetchone()
        trade_count = connection.execute("SELECT COUNT(*) AS count FROM trades").fetchone()
        frozen_users = connection.execute("SELECT COUNT(*) AS count FROM users WHERE is_frozen = 1").fetchone()
        recent_users = connection.execute(
            """
            SELECT user_id, user_name, wallet_address, is_admin, is_frozen, created_at
            FROM users
            ORDER BY updated_at DESC
            LIMIT 50
            """
        ).fetchall()
    return {
        "stats": {
            "users": int(user_count["count"]) if user_count else 0,
            "open_orders": int(open_orders_count["count"]) if open_orders_count else 0,
            "trades": int(trade_count["count"]) if trade_count else 0,
            "frozen_users": int(frozen_users["count"]) if frozen_users else 0,
        },
        "users": [dict(row) for row in recent_users],
    }


@app.post("/api/admin/users/freeze")
def admin_freeze_user(payload: AdminFreezeRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        require_admin(connection, payload.admin_user_id)
        connection.execute(
            "UPDATE users SET is_frozen = ?, updated_at = ? WHERE user_id = ?",
            (1 if payload.freeze else 0, utc_now(), payload.target_user_id),
        )
        action = "ADMIN_FREEZE" if payload.freeze else "ADMIN_UNFREEZE"
        log_history(
            connection,
            "LIMIT",
            payload.admin_user_id,
            None,
            f"{action} target={payload.target_user_id} reason={payload.reason}",
        )
        connection.commit()
    return {"status": "ok", "target_user_id": payload.target_user_id, "is_frozen": payload.freeze}


@app.post("/api/admin/users/role")
def admin_set_role(payload: AdminSetRoleRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        require_admin(connection, payload.admin_user_id)
        connection.execute(
            "UPDATE users SET is_admin = ?, updated_at = ? WHERE user_id = ?",
            (1 if payload.is_admin else 0, utc_now(), payload.target_user_id),
        )
        log_history(
            connection,
            "LIMIT",
            payload.admin_user_id,
            None,
            f"ADMIN_SET_ROLE target={payload.target_user_id} is_admin={payload.is_admin}",
        )
        connection.commit()
    return {"status": "ok", "target_user_id": payload.target_user_id, "is_admin": payload.is_admin}


@app.post("/api/admin/balances/adjust")
def admin_adjust_balance(payload: AdminAdjustBalanceRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        require_admin(connection, payload.admin_user_id)
        asset = payload.asset.upper()
        current = get_cash_balance(connection, payload.target_user_id, asset)
        next_amount = current + payload.delta
        if next_amount < 0:
            raise HTTPException(status_code=400, detail="Adjustment would make balance negative.")
        set_cash_balance(connection, payload.target_user_id, asset, next_amount)
        connection.execute(
            """
            INSERT INTO payment_transactions (user_id, action, asset, amount, status, reference, created_at)
            VALUES (?, 'ADMIN_ADJUST', ?, ?, 'SUCCESS', ?, ?)
            """,
            (
                payload.target_user_id,
                asset,
                payload.delta,
                f"admin:{payload.admin_user_id}:{payload.reason}",
                utc_now(),
            ),
        )
        log_history(
            connection,
            "LIMIT",
            payload.admin_user_id,
            None,
            f"ADMIN_ADJUST user={payload.target_user_id} asset={asset} delta={payload.delta} reason={payload.reason}",
        )
        connection.commit()
    return {"status": "ok", "target_user_id": payload.target_user_id, "asset": asset, "balance": next_amount}
