from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from deps import AdminUser, DbSession, get_current_user
from models import User
from schema import UserCreate, UserResponse
from security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse], dependencies=[Depends(get_current_user)])
async def list_users(db: DbSession):
    result = await db.scalars(select(User).order_by(User.username))
    return result.all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: DbSession, _admin: AdminUser):
    user = User(
        username=payload.username,
        hashed_password=await run_in_threadpool(hash_password, payload.password),
        role=payload.role,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
        ) from None
    return user
