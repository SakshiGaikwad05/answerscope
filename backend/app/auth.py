"""Accounts and sessions.

- Passwords are hashed with scrypt (Python standard library) and a per-user salt.
- Sessions are random 256-bit tokens in an httpOnly, SameSite=Lax cookie; only a
  SHA-256 hash of the token is stored, so a database leak doesn't expose sessions.
- The frontend calls the API through its own origin, so the cookie is first-party.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Project, User, UserSession

SESSION_COOKIE = "aeo_session"
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}$")
# scrypt parameters (~16 MB memory, fast enough for a login request)
_N, _R, _P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    return email


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        digest = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, user: User, response: Response) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token), expires_at=now + timedelta(days=settings.session_days)))
    # Opportunistically clean up this user's expired sessions.
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))
    if session is None:
        return None
    expires = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    return db.get(User, session.user_id)


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in to continue")
    return user


def claim_unowned_projects(db: Session, user: User) -> int:
    """Projects created before accounts existed belong to the first account created."""
    if db.scalar(select(User.id).where(User.id != user.id).limit(1)) is not None:
        return 0
    result = db.execute(update(Project).where(Project.user_id.is_(None)).values(user_id=user.id))
    db.commit()
    return result.rowcount or 0
