import sqlite3
from threading import Lock

from .config import settings
from .time import utc_now

DB_LOCK = Lock()


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.db_path, check_same_thread=False)
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
        if "email" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "password_hash" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        if "solana_wallet_encrypted" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN solana_wallet_encrypted TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(lower(email)) WHERE email IS NOT NULL")
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
        market_columns = [row["name"] for row in connection.execute("PRAGMA table_info(markets)").fetchall()]
        if "question" not in market_columns:
            connection.execute("ALTER TABLE markets ADD COLUMN question TEXT NOT NULL DEFAULT ''")
        if "description" not in market_columns:
            connection.execute("ALTER TABLE markets ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if "market_type" not in market_columns:
            connection.execute("ALTER TABLE markets ADD COLUMN market_type TEXT NOT NULL DEFAULT 'BINARY'")
        if "resolved_outcome" not in market_columns:
            connection.execute("ALTER TABLE markets ADD COLUMN resolved_outcome TEXT")
        if "resolved_at" not in market_columns:
            connection.execute("ALTER TABLE markets ADD COLUMN resolved_at TEXT")
        order_columns = [row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()]
        if "outcome" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN outcome TEXT NOT NULL DEFAULT 'YES'")
        existing_markets = connection.execute("SELECT COUNT(*) AS count FROM markets").fetchone()
        if existing_markets and int(existing_markets["count"]) == 0:
            now = utc_now()
            connection.execute(
                """
                INSERT INTO markets (
                    symbol, name, question, description, status, tick_size, min_order_size, market_type, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'OPEN', ?, ?, 'BINARY', ?, ?)
                """,
                (
                    "BTC-100K-2026",
                    "Bitcoin above 100k in 2026",
                    "Will Bitcoin trade above 100,000 USD before the end of 2026?",
                    "Binary YES/NO prediction market seeded for public discovery.",
                    0.01,
                    1,
                    now,
                    now,
                ),
            )
        connection.commit()


def initialize_schema() -> None:
    init_db()
    init_users_table()
    init_admin_emails_table()
    init_trades_table()
    init_markets_table()
