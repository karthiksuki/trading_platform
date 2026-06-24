from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from app.core.database import DB_LOCK, get_connection
from app.core.time import utc_now
from app.services.accounts import require_active_user
from app.services.trading import (
    coerce_payment_payload,
    fetch_cached_idempotent_response,
    get_cash_balance,
    log_history,
    run_with_retry,
    save_idempotent_response,
    set_cash_balance,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/deposit")
def deposit(
    payload: Any = Body(...), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    payment = coerce_payment_payload(payload)

    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            require_active_user(connection, payment.user_id)
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


@router.post("/withdraw")
def withdraw(
    payload: Any = Body(...), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> dict[str, str | float | int]:
    payment = coerce_payment_payload(payload)

    def operation() -> dict[str, str | float | int]:
        with DB_LOCK, get_connection() as connection:
            require_active_user(connection, payment.user_id)
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


@router.get("/transactions")
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


@router.get("/balances/{user_id}")
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
