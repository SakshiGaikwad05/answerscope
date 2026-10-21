"""Usage quotas for paid AI actions, and simple request rate limiting.

Quotas are counted from the usage_events table over a rolling 24 hours, per user
and across all users (a global ceiling on what the server's API key is used for).

The rate limiter is in-memory: it protects a single API process. Behind several
processes or machines, put a shared limiter (e.g. at the reverse proxy) in front.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import UsageEvent, User

QUOTA_KINDS = ("visibility_run", "question_generation", "fix_generation", "backlink_discovery")


def _limits(kind: str) -> tuple[int, int]:
    s = get_settings()
    return {
        "visibility_run": (s.quota_visibility_runs_per_user_per_day, s.quota_visibility_runs_global_per_day),
        "question_generation": (s.quota_question_generations_per_user_per_day, s.quota_question_generations_global_per_day),
        "fix_generation": (s.quota_fix_generations_per_user_per_day, s.quota_fix_generations_global_per_day),
        "backlink_discovery": (s.quota_backlink_discoveries_per_user_per_day, s.quota_backlink_discoveries_global_per_day),
    }[kind]


def _count(db: Session, kind: str, user_id: int | None = None) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    q = select(func.count()).select_from(UsageEvent).where(UsageEvent.kind == kind, UsageEvent.created_at >= since)
    if user_id is not None:
        q = q.where(UsageEvent.user_id == user_id)
    else:
        # The global cap protects the server's own API keys; users' own keys don't count toward it
        q = q.where(UsageEvent.own_key.is_(False))
    return db.scalar(q) or 0


def usage_summary(db: Session, user: User) -> dict:
    out = {}
    for kind in QUOTA_KINDS:
        per_user, global_cap = _limits(kind)
        used = _count(db, kind, user.id)
        out[kind] = {"used": used, "limit": per_user, "remaining": max(per_user - used, 0)}
    return out


def consume_quota(db: Session, user: User, kind: str, *, own_key: bool = False) -> None:
    """Record one use of a paid action, or raise 429 if a limit is reached. Caller commits.

    own_key: the action runs on the user's own API key, so the server-wide cap doesn't apply.
    """
    per_user, global_cap = _limits(kind)
    label = kind.replace("_", " ")
    if _count(db, kind, user.id) >= per_user:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": "quota_exceeded", "message": f"Daily limit reached: {per_user} {label}s per 24 hours. Try again later."},
        )
    if not own_key and _count(db, kind) >= global_cap:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": "global_quota_exceeded", "message": f"The service's daily {label} capacity is used up. Try again tomorrow."},
        )
    db.add(UsageEvent(user_id=user.id, kind=kind, own_key=own_key))


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                retry = int(window - (now - hits[0])) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    {"code": "rate_limited", "message": f"Too many requests. Try again in {retry} seconds."},
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Behind a proxy secret, the frontend passes the visitor's address in x-aeo-client-ip (checked in main.py).
    if get_settings().has_key(get_settings().proxy_secret):
        return request.headers.get("x-aeo-client-ip", "").strip() or "unknown"
    # Local / docker-compose: the Next.js proxy forwards the browser's address in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def limit_auth(request: Request) -> None:
    limiter.check(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)


def limit_writes(key: str) -> None:
    limiter.check(f"write:{key}", get_settings().rate_limit_writes_per_minute)
