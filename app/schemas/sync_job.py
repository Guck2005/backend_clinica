from datetime import datetime

from pydantic import BaseModel


class SyncJobRead(BaseModel):
    id: int
    job_type: str
    entity_type: str
    entity_id: str
    payload: dict | None
    status: str
    retry_count: int
    last_error: str | None
    scheduled_at: datetime
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
