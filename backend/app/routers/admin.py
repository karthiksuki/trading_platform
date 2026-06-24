from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.database import DB_LOCK, get_connection
from app.core.time import utc_now
from app.schemas import (
    AdminAccessGrantRequest,
    AdminAdjustBalanceRequest,
    AdminCreateMarketRequest,
    AdminFreezeRequest,
    AdminMarketStatusRequest,
    AdminReconcileRequest,
    AdminRiskRecalcRequest,
    AdminSetRoleRequest,
    AdminStaleCleanupRequest,
)
from app.services.accounts import require_admin, require_admin_credentials
from app.services.markets import fetch_orderbook_for_outcome
from app.services.trading import get_cash_balance, log_history, set_cash_balance

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/access_grant")
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


@router.post("/markets")
def admin_create_market(payload: AdminCreateMarketRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        admin_email = require_admin_credentials(connection, payload.admin_email, payload.admin_password)
        now = utc_now()
        question = payload.question.strip() or payload.name
        cursor = connection.execute(
            """
            INSERT INTO markets (
                symbol, name, question, description, status, tick_size, min_order_size, market_type, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'OPEN', ?, ?, 'BINARY', ?, ?)
            """,
            (
                payload.symbol.upper(),
                payload.name,
                question,
                payload.description,
                payload.tick_size,
                payload.min_order_size,
                now,
                now,
            ),
        )
        market_id = int(cursor.lastrowid)
        log_history(
            connection,
            "ADMIN_MARKET_CREATE",
            admin_email,
            market_id,
            f"Created prediction market {payload.symbol.upper()} ({question})",
        )
        connection.commit()
    return {"status": "created", "market_id": market_id}


@router.get("/markets")
def admin_list_markets(admin_email: str, admin_password: str) -> list[dict[str, Any]]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        rows = connection.execute(
            """
            SELECT id, symbol, name, question, description, status, tick_size, min_order_size,
                   market_type, resolved_outcome, resolved_at, created_at, updated_at
            FROM markets
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/markets/{market_id}/status")
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


@router.get("/monitoring/summary")
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


@router.get("/monitoring/logs")
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


@router.get("/monitoring/market-health")
def admin_market_health(admin_email: str, admin_password: str) -> list[dict[str, Any]]:
    with DB_LOCK, get_connection() as connection:
        require_admin_credentials(connection, admin_email, admin_password)
        markets = connection.execute(
            "SELECT id, symbol, name, question, status FROM markets ORDER BY id DESC"
        ).fetchall()
        payload: list[dict[str, Any]] = []
        for market in markets:
            yes_book = fetch_orderbook_for_outcome(connection, int(market["id"]), "YES")
            no_book = fetch_orderbook_for_outcome(connection, int(market["id"]), "NO")
            last_trade = connection.execute(
                """
                SELECT t.created_at, t.execution_price, o.outcome
                FROM trades t
                JOIN orders o ON o.id = t.buy_order_id
                WHERE t.market_id = ?
                ORDER BY t.created_at DESC
                LIMIT 1
                """,
                (int(market["id"]),),
            ).fetchone()
            bid = yes_book["best_bid"]
            ask = yes_book["best_ask"]
            spread = (ask - bid) if bid is not None and ask is not None else None
            payload.append(
                {
                    "market_id": int(market["id"]),
                    "symbol": str(market["symbol"]),
                    "name": str(market["name"]),
                    "question": str(market["question"] or market["name"]),
                    "status": str(market["status"]),
                    "best_bid": bid,
                    "best_ask": ask,
                    "yes_best_bid": yes_book["best_bid"],
                    "yes_best_ask": yes_book["best_ask"],
                    "no_best_bid": no_book["best_bid"],
                    "no_best_ask": no_book["best_ask"],
                    "spread": spread,
                    "last_trade_at": str(last_trade["created_at"]) if last_trade else None,
                    "last_trade_price": float(last_trade["execution_price"]) if last_trade else None,
                    "last_trade_outcome": str(last_trade["outcome"]) if last_trade else None,
                }
            )
    return payload


@router.post("/ops/stale-order-cleanup")
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


@router.post("/ops/reconcile")
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


@router.post("/ops/risk-recalc")
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


@router.get("/overview")
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


@router.post("/users/freeze")
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


@router.post("/users/role")
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


@router.post("/balances/adjust")
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
