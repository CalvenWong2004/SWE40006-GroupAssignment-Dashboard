from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from deps import AdminUser, DbSession, get_current_user
from models import Task, User
from schema import TaskCreate, TaskPage, TaskResponse, TaskUpdate

# Every route in this router requires a valid token.
router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(get_current_user)])


async def _load_task(db: DbSession, task_id: int) -> Task | None:
    # populate_existing makes sure the `assignee` relationship is (re)loaded even
    # when the Task is already in the session, e.g. right after creating it.
    return await db.scalar(
        select(Task)
        .options(selectinload(Task.assignee))
        .where(Task.id == task_id)
        .execution_options(populate_existing=True)
    )


async def _get_task_or_404(db: DbSession, task_id: int) -> Task:
    task = await _load_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


async def _ensure_assignee_exists(db: DbSession, assignee_id: int | None) -> None:
    if assignee_id is None:
        return
    if await db.get(User, assignee_id) is None:
        raise HTTPException(
            status_code=422,
            detail=f"Assignee {assignee_id} does not exist",
        )


@router.get("", response_model=TaskPage)
async def list_tasks(
    db: DbSession,
    is_completed: bool | None = None,
    assignee_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = []
    if is_completed is not None:
        filters.append(Task.is_completed == is_completed)
    if assignee_id is not None:
        filters.append(Task.assignee_id == assignee_id)

    total = await db.scalar(select(func.count()).select_from(Task).where(*filters))
    result = await db.scalars(
        select(Task)
        .options(selectinload(Task.assignee))
        .where(*filters)
        .order_by(Task.id)
        .limit(limit)
        .offset(offset)
    )
    return TaskPage(items=result.all(), total=total or 0, limit=limit, offset=offset)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreate, db: DbSession):
    await _ensure_assignee_exists(db, payload.assignee_id)
    task = Task(
        description=payload.description,
        priority=payload.priority,
        status=payload.status,
        is_completed=payload.status == "Done",
        assignee_id=payload.assignee_id,
    )
    db.add(task)
    await db.commit()
    return await _load_task(db, task.id)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: DbSession):
    return await _get_task_or_404(db, task_id)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: int, payload: TaskUpdate, db: DbSession):
    task = await _get_task_or_404(db, task_id)

    changes = payload.model_dump(exclude_unset=True)
    # Only assignee_id may be set to null (to un-assign); null elsewhere is ignored.
    changes = {k: v for k, v in changes.items() if v is not None or k == "assignee_id"}

    if "assignee_id" in changes:
        await _ensure_assignee_exists(db, changes["assignee_id"])

    for field, value in changes.items():
        setattr(task, field, value)

    # Keep `status` and `is_completed` consistent (the schema already rejects
    # requests that set both to conflicting values).
    if "status" in changes and "is_completed" not in changes:
        task.is_completed = task.status == "Done"
    elif "is_completed" in changes and "status" not in changes:
        if task.is_completed:
            task.status = "Done"
        elif task.status == "Done":
            task.status = "To Do"

    await db.commit()
    return await _load_task(db, task_id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: DbSession, _admin: AdminUser):
    task = await _get_task_or_404(db, task_id)
    await db.delete(task)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
