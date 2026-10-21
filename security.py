import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, status

from config import settings


# ---------- passwords ----------
# bcrypt is CPU-bound: call these through starlette's run_in_threadpool from async code.
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:  # e.g. password longer than bcrypt's 72-byte limit
        return False


# Verified against when the username doesn't exist, so response time doesn't
# reveal which usernames are real.
DUMMY_HASH = hash_password("dummy-password-for-timing")


# ---------- JWT ----------
def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )


# ---------- login rate limiting ----------
class LoginRateLimiter:
    """In-memory sliding window of failed logins per key (client IP).

    Per-process only. With several workers or servers, use a shared store
    (Redis / slowapi) instead. Behind a reverse proxy, run uvicorn with
    --proxy-headers so the key is the real client IP.
    """

    def __init__(self, max_failures: int, window_seconds: int):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] > self.window:
            attempts.popleft()
        if not attempts:
            self._failures.pop(key, None)
        return attempts

    def check(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._prune(key, now)
        if len(attempts) >= self.max_failures:
            retry_after = int(self.window - (now - attempts[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    def fail(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()


login_limiter = LoginRateLimiter(settings.login_max_failures, settings.login_window_seconds)
