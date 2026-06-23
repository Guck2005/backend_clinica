from datetime import datetime

from pydantic import BaseModel


class AlertRead(BaseModel):
    code: str
    rule_code: str
    rule_name: str
    gravite: str
    message: str
    caisse_id: int | None
    source_type: str
    source_id: str
    details: dict | None
    impact_amount_fcfa: int | None
    status: str
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None
    notification_email_status: str | None
    notification_email_sent_at: datetime | None
    created_at: datetime
    active: bool


class AlertListResponse(BaseModel):
    items: list[AlertRead]
    total: int


class AlertResolveRequest(BaseModel):
    resolution_note: str | None = None
