import sqlite3
from typing import Any

from fastapi import HTTPException

from app.core.security import decrypt_text


def require_active_user(connection: sqlite3.Connection, user_id: str) -> None:
    row = connection.execute(
        "SELECT user_id, is_frozen FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Create an account before trading.")
    if int(row["is_frozen"]) == 1:
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


def serialize_user_account(row: sqlite3.Row) -> dict[str, Any]:
    encrypted_solana = row["solana_wallet_encrypted"] if "solana_wallet_encrypted" in row.keys() else None
    try:
        solana_wallet_address = decrypt_text(encrypted_solana)
    except Exception:
        solana_wallet_address = None
    return {
        "user_id": str(row["user_id"]),
        "email": row["email"] if "email" in row.keys() else None,
        "user_name": str(row["user_name"]),
        "user_profile": str(row["user_profile"] or ""),
        "wallet_address": str(row["wallet_address"]),
        "solana_wallet_address": solana_wallet_address,
        "is_admin": int(row["is_admin"]) if "is_admin" in row.keys() else 0,
        "is_frozen": int(row["is_frozen"]) if "is_frozen" in row.keys() else 0,
    }
