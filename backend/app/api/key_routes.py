"""Users' own provider API keys: list (masked), save (encrypted, checked when possible), delete."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.limits import limit_writes
from app.models import User
from app.services import user_keys

router = APIRouter(prefix="/api")


class KeyIn(BaseModel):
    api_key: str


def _raise(err: user_keys.UserKeyError):
    raise HTTPException(err.status, {"code": err.code, "message": err.message}) from None


@router.get("/keys")
def list_keys(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        return user_keys.key_status(db, user.id)
    except user_keys.UserKeyError as err:
        _raise(err)


@router.put("/keys/{provider}")
def save_key(provider: str, payload: KeyIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    limit_writes(f"user:{user.id}")
    try:
        user_keys.save_key(db, user.id, provider, payload.api_key)
        return user_keys.key_status(db, user.id)
    except user_keys.UserKeyError as err:
        _raise(err)


@router.delete("/keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(provider: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    limit_writes(f"user:{user.id}")
    if provider not in user_keys.KEY_SPECS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    user_keys.delete_key(db, user.id, provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
