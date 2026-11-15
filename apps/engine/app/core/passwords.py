"""Password policy. Length is the main control; this adds a short denylist and obvious-pattern checks."""

import re

MIN_LENGTH = 10
MAX_LENGTH = 128
_COMMON = frozenset(
    """
    password123 1234567890 12345678910 qwertyuiop iloveyou123 welcome123 administrator letmein1234 password1234
    0123456789 1q2w3e4r5t abcdefghij passw0rd123 changeme123 qazwsxedc1 qwerty12345 password12345 1234567891
    1111111111 0000000000 abcdefg123 monkey12345 dragon12345 football123 baseball123 trustno1234 superman123
    """.split()
)


def check_password(password: str, email: str | None = None) -> str | None:
    """Return a user-facing reason the password is not acceptable, or None."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters."
    low = password.lower()
    if low in _COMMON or re.sub(r"[^a-z0-9]", "", low) in _COMMON:
        return "That password is too common. Choose something less guessable."
    if len(set(password)) < 4:
        return "Password needs more variety of characters."
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 4 and local in low:
            return "Password must not contain your email name."
    return None
