import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet
from datetime import datetime, timedelta, timezone

from .config import settings


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return base64.urlsafe_b64encode(salt + digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(encoded.encode())
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), raw[:16], 210_000), raw[16:])
    except (ValueError, TypeError):
        return False


def issue_token(user_id: int) -> str:
    expires = int((datetime.now(timezone.utc) + timedelta(hours=settings.token_ttl_hours)).timestamp())
    payload = f"{user_id}:{expires}"
    signature = hmac.new(settings.token_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def read_token(token: str) -> int | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        user, expires, signature = decoded.split(":", 2)
        payload = f"{user}:{expires}"
        expected = hmac.new(settings.token_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return int(user)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.token_secret.encode()).digest())
    return Fernet(key)


def sign_webhook(secret: str, timestamp: str, body: str) -> str:
    message = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def new_api_key(mode: str = "test") -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    prefix = "fp_live_" if mode == "live" else "fp_test_"
    value = prefix + raw
    return value, hashlib.sha256(value.encode()).hexdigest()
