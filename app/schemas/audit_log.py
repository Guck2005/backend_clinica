from datetime import date, datetime

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: int
    action_code: str
    action_label: str
    actor_id: int | None
    actor_nom_snapshot: str | None
    actor_role_snapshot: str | None
    entity_type: str
    entity_id: str
    caisse_id: int | None
    detail: dict | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int


class AuditLogFilterParams(BaseModel):
    action_code: str | None = None
    actor_role: str | None = None
    caisse_id: int | None = None
    search: str | None = None
    date_from: date | None = None
    date_to: date | None = None
