from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    MIN_PASSWORD_LENGTH,
    claim_unowned_projects,
    current_user,
    end_session,
    hash_password,
    normalize_email,
    start_session,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.limits import limit_auth
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth")

# Verified against when the email doesn't exist, so response time doesn't reveal which emails have accounts.
_DUMMY_HASH = hash_password("not-a-real-password")


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        return v


class UserOut(BaseModel):
    id: int
    email: str


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: Registration, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    limit_auth(request)
    if not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed")
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists. Log in instead.")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    claimed = claim_unowned_projects(db, user)
    if claimed:
        logger.info("user %s claimed %s pre-existing project(s)", user.id, claimed)
    start_session(db, user, response)
    logger.info("registered user %s", user.id)
    return {"id": user.id, "email": user.email}


@router.post("/login", response_model=UserOut)
def login(payload: Credentials, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    limit_auth(request)
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        verify_password(payload.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    start_session(db, user, response)
    return {"id": user.id, "email": user.email}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    end_session(db, request, response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email}
