import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from .config import settings


def get_cipher() -> Fernet:
    digest = hashlib.sha256(settings.trading_encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(value: str | None) -> str | None:
    if not value:
        return None
    return get_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str | None) -> str | None:
    if not value:
        return None
    return get_cipher().decrypt(value.encode("utf-8")).decode("utf-8")


def hash_password(password: str) -> str:
    iterations = 260_000
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations_raw, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations_raw),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (TypeError, ValueError):
        return False
