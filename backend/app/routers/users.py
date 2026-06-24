from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.core.database import DB_LOCK, get_connection
from app.core.security import encrypt_text, hash_password, verify_password
from app.core.time import utc_now
from app.schemas import LocalSigninRequest, LocalSignupRequest, OnboardingRequest
from app.services.accounts import serialize_user_account
from app.services.trading import log_history, set_cash_balance

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("/onboard")
def onboard_user(payload: OnboardingRequest) -> dict[str, str]:
    with DB_LOCK, get_connection() as connection:
        now = utc_now()
        existing = connection.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (payload.user_id,),
        ).fetchone()
        if existing:
            status = "exists"
            return {"status": status, "user_id": payload.user_id}

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


@router.post("/signup")
def signup_user(payload: LocalSignupRequest) -> dict[str, Any]:
    with DB_LOCK, get_connection() as connection:
        now = utc_now()
        email = payload.email.strip().lower()
        existing = connection.execute("SELECT user_id FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered.")
        user_id = f"local:{uuid4().hex[:12]}"
        wallet_address = payload.solana_wallet_address.strip() or user_id
        encrypted_solana = encrypt_text(payload.solana_wallet_address.strip()) if payload.solana_wallet_address.strip() else None
        connection.execute(
            """
            INSERT INTO users (
                user_id, wallet_address, email, password_hash, user_name, user_profile, profile_picture,
                solana_wallet_encrypted, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                wallet_address,
                email,
                hash_password(payload.password),
                payload.user_name,
                payload.user_profile,
                payload.profile_picture,
                encrypted_solana,
                now,
                now,
            ),
        )
        set_cash_balance(connection, user_id, "USD", 10000.0)
        log_history(connection, "SIGNUP", user_id, None, f"Local signup for {payload.user_name}")
        row = connection.execute(
            """
            SELECT user_id, wallet_address, email, user_name, user_profile, solana_wallet_encrypted, is_admin, is_frozen
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        connection.commit()
    return {"status": "created", "account": serialize_user_account(row), "starting_balance": 10000.0}


@router.post("/signin")
def signin_user(payload: LocalSigninRequest) -> dict[str, Any]:
    email = payload.email.strip().lower()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, wallet_address, email, password_hash, user_name, user_profile,
                   solana_wallet_encrypted, is_admin, is_frozen
            FROM users
            WHERE lower(email) = ?
            """,
            (email,),
        ).fetchone()
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if int(row["is_frozen"]) == 1:
        raise HTTPException(status_code=403, detail="Account is frozen by admin.")
    return {"status": "ok", "account": serialize_user_account(row)}


@router.get("/{user_id}")
def get_user(user_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, wallet_address, email, user_name, user_profile, profile_picture,
                   solana_wallet_encrypted, is_admin, is_frozen, created_at, updated_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found.")
    return serialize_user_account(row)
