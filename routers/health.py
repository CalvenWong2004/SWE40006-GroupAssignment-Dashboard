from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness: the process is up and serving. Deliberately does not touch the database,
    so a database outage restarts nothing."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: DbSession):
    """Readiness: the app can reach its database. Kubernetes only routes traffic to
    pods that pass this, which is what keeps a rolling update free of downtime."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
        ) from None
    return {"status": "ready"}
