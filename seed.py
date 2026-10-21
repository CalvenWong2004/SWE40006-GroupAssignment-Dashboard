import logging

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from config import settings
from database import AsyncSessionLocal
from models import User
from security import hash_password

logger = logging.getLogger(__name__)


async def seed_demo_users() -> None:
    """Create demo users when the users table is empty. Development only."""
    if not settings.seed_password:
        raise RuntimeError("SEED_DEMO_USERS is enabled but SEED_PASSWORD is not set")

    async with AsyncSessionLocal() as session:
        if await session.scalar(select(User.id).limit(1)) is not None:
            return

        hashed = await run_in_threadpool(hash_password, settings.seed_password)
        session.add_all(
            [
                User(username="Calven", hashed_password=hashed, role="admin"),
                User(username="Mahymar", hashed_password=hashed, role="user"),
                User(username="Sothearith", hashed_password=hashed, role="user"),
            ]
        )
        try:
            await session.commit()
            logger.info("Seeded demo users")
        except IntegrityError:
            # Another worker seeded at the same moment; nothing to do.
            await session.rollback()
