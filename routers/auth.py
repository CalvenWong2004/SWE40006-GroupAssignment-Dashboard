from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from deps import DbSession
from models import User
from schema import Token
from security import DUMMY_HASH, create_access_token, login_limiter, verify_password

router = APIRouter(tags=["auth"])


@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
):
    """Standard OAuth2 password flow: form-encoded `username` and `password`."""
    client_key = request.client.host if request.client else "unknown"
    login_limiter.check(client_key)

    user = await db.scalar(select(User).where(User.username == form.username))
    hashed = user.hashed_password if user else DUMMY_HASH
    password_ok = await run_in_threadpool(verify_password, form.password, hashed)

    if user is None or not password_ok:
        login_limiter.fail(client_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    login_limiter.reset(client_key)
    return Token(access_token=create_access_token(user.id), role=user.role)
