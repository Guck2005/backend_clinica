from datetime import datetime

from pydantic import BaseModel, Field


class BackupSettingsRead(BaseModel):
    enabled: bool
    frequency_minutes: int
    target_directory: str
    retention_count: int
    updated_by_id: int | None
    updated_at: datetime | None
    supported: bool
    support_message: str | None = None


class BackupSettingsUpdate(BaseModel):
    enabled: bool | None = None
    frequency_minutes: int | None = Field(default=None, ge=5)
    target_directory: str | None = None
    retention_count: int | None = Field(default=None, ge=1, le=365)


class BackupRunRead(BaseModel):
    id: int
    status: str
    file_path: str | None
    file_size_bytes: int | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class BackupRunListResponse(BaseModel):
    items: list[BackupRunRead]
    total: int
