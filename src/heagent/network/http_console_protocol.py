"""Bounded console request models and the injected project-handler contract."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_PROJECT_NAME_CHARS = 64
MAX_PROJECT_PATH_CHARS = 4096


class ProjectEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)
    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    available: bool
    last_opened_at: str | None = None
    is_default: bool


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[ProjectEntryResponse] = Field(max_length=32)


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=MAX_PROJECT_PATH_CHARS)
    name: str | None = Field(default=None, max_length=MAX_PROJECT_NAME_CHARS)

    @field_validator("path", "name", mode="before")
    @classmethod
    def _strip_string(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_PROJECT_NAME_CHARS)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ConsoleOperationError(Exception):
    """Expected handler failure with a stable client-visible code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConsoleHandler(Protocol):
    """Project operations supplied by the entry layer; network knows no registry."""

    async def list_projects(self) -> ProjectListResponse: ...

    async def register_project(self, request: ProjectRegisterRequest) -> ProjectEntryResponse: ...

    async def rename_project(self, project_id: str, request: ProjectRenameRequest) -> ProjectEntryResponse: ...

    async def project_has_inflight_run(self, project_id: str) -> bool: ...

    async def remove_project(self, project_id: str) -> None: ...


__all__ = [
    "ConsoleHandler",
    "ConsoleOperationError",
    "ProjectEntryResponse",
    "ProjectListResponse",
    "ProjectRegisterRequest",
    "ProjectRenameRequest",
]
