"""Pydantic request/response models mirroring the API shapes of SPEC §5."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# --- auth / users ---

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    is_admin: bool


class AdminUserOut(UserOut):
    disabled: bool
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    is_admin: bool = False


class AdminUserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=128)
    is_admin: bool | None = None
    disabled: bool | None = None


# --- files ---

class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    orig_name: str
    size: int
    mime: str
    created_at: datetime
    expires_at: datetime | None


# --- tools ---

class ToolInfo(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    accepts: list[str]
    multi_file: bool
    min_files: int
    params_schema: dict
    queue: str
    available: bool
    unavailable_reason: str | None


# --- jobs ---

class JobCreate(BaseModel):
    tool: str = Field(min_length=1, max_length=64)
    file_ids: list[UUID] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)


class JobOut(BaseModel):
    id: UUID
    tool: str
    status: str
    progress: float
    message: str | None
    params: dict
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    input_files: list[FileInfo]
    output_files: list[FileInfo]


class JobList(BaseModel):
    items: list[JobOut]
    total: int


# --- admin ---

class AdminStats(BaseModel):
    users: int
    jobs_total: int
    jobs_by_status: dict[str, int]
    disk_used_bytes: int
    queue_depth: dict[str, int]
