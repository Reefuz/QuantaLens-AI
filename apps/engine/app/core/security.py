"""Password hashing and session token primitives."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)

# Verified against when an email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = _hasher.hash("quantalens-timing-equalisation")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """HMAC-SHA256 keyed with AUTH_SECRET. A copy of the sessions table alone cannot be used to look up or forge tokens."""
    from app.config import get_settings

    key = get_settings().auth_secret.get_secret_value().encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
