from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

Priority = Literal["High", "Medium", "Low"]
Status = Literal["To Do", "In Progress", "Done"]
Role = Literal["user", "admin"]

Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]


# ---------- auth / users ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserCreate(BaseModel):
    username: Username
    password: str
    role: Role = "user"

    @field_validator("password")
    @classmethod
    def _password_rules(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(value.encode("utf-8")) > 72:  # bcrypt limit
            raise ValueError("Password must be at most 72 bytes")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


# ---------- tasks ----------
class TaskCreate(BaseModel):
    description: Description
    priority: Priority = "Medium"
    status: Status = "To Do"
    assignee_id: int | None = None


class TaskUpdate(BaseModel):
    """Partial update: only fields present in the request body are changed."""

    description: Description | None = None
    priority: Priority | None = None
    status: Status | None = None
    is_completed: bool | None = None
    assignee_id: int | None = None  # explicit null un-assigns the task

    @model_validator(mode="after")
    def _status_matches_completed(self):
        if (
            self.status is not None
            and self.is_completed is not None
            and (self.status == "Done") != self.is_completed
        ):
            raise ValueError("status and is_completed disagree")
        return self


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    priority: str
    status: str
    is_completed: bool
    assignee_id: int | None
    assignee: UserResponse | None = None


class TaskPage(BaseModel):
    items: list[TaskResponse]
    total: int
    limit: int
    offset: int
