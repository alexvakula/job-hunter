"""Password hashing and account-field policy (FR-002b)."""

import re

import bcrypt

USERNAME_RE = re.compile(r"^[a-z0-9]{2,32}$")
MIN_PASSWORD_LENGTH = 12
_BCRYPT_ROUNDS = 12
# bcrypt only looks at the first 72 bytes; reject longer input rather than silently truncating.
_MAX_PASSWORD_BYTES = 72


class PolicyError(ValueError):
    pass


def validate_username(username: str) -> str:
    if not USERNAME_RE.fullmatch(username or ""):
        raise PolicyError("Username must be 2–32 lower-case letters or digits.")
    return username


def validate_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise PolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode()) > _MAX_PASSWORD_BYTES:
        raise PolicyError("Password is too long (maximum 72 bytes).")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:_MAX_PASSWORD_BYTES], password_hash.encode())
    except ValueError:
        return False


# Used to spend the same time on unknown usernames as on wrong passwords.
DUMMY_HASH = hash_password("dummy-password-for-timing")
