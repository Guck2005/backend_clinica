from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.reporting import render_csv, render_xlsx
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogListResponse, AuditLogRead


router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def audit_log_to_read(entry: AuditLog) -> AuditLogRead:
    return AuditLogRead(
        id=entry.id,
        action_code=entry.action_code,
        action_label=entry.action_label,
        actor_id=entry.actor_id,
        actor_nom_snapshot=entry.actor_nom_snapshot,
        actor_role_snapshot=entry.actor_role_snapshot,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        caisse_id=entry.caisse_id,
        detail=entry.detail_json,
        created_at=entry.created_at,
    )


def filtered_audit_logs(
    db: Session,
    *,
    action_code: str | None,
    actor_role: str | None,
    caisse_id: int | None,
    search: str | None,
    date_from: date | None,
    date_to: date | None,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if action_code:
        query = query.where(AuditLog.action_code == action_code.strip())
    if actor_role:
        query = query.where(AuditLog.actor_role_snapshot == actor_role.strip())
    if caisse_id is not None:
        query = query.where(AuditLog.caisse_id == caisse_id)
    if date_from is not None:
        query = query.where(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        query = query.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                AuditLog.action_label.ilike(pattern),
                AuditLog.actor_nom_snapshot.ilike(pattern),
                AuditLog.entity_type.ilike(pattern),
                AuditLog.entity_id.ilike(pattern),
            )
        )
    return db.scalars(query).all()


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    action_code: str | None = None,
    actor_role: str | None = None,
    caisse_id: int | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_roles("auditeur", "superviseur", "admin")),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    items = filtered_audit_logs(
        db,
        action_code=action_code,
        actor_role=actor_role,
        caisse_id=caisse_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return AuditLogListResponse(
        items=[audit_log_to_read(item) for item in page_items],
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.get("/export")
def export_audit_logs(
    format: str = Query(..., pattern="^(csv|xlsx)$"),
    action_code: str | None = None,
    actor_role: str | None = None,
    caisse_id: int | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_roles("auditeur", "superviseur", "admin")),
    db: Session = Depends(get_db),
) -> Response:
    items = filtered_audit_logs(
        db,
        action_code=action_code,
        actor_role=actor_role,
        caisse_id=caisse_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    rows = [
        {
            "id": item.id,
            "action_code": item.action_code,
            "action_label": item.action_label,
            "actor_nom": item.actor_nom_snapshot,
            "actor_role": item.actor_role_snapshot,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "caisse_id": item.caisse_id,
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]
    fields = ["id", "action_code", "action_label", "actor_nom", "actor_role", "entity_type", "entity_id", "caisse_id", "created_at"]
    if format == "csv":
        content = render_csv(rows, fields)
        media_type = "text/csv; charset=utf-8"
    else:
        content = render_xlsx("journal_audit", rows, fields)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="journal-audit.{format}"'},
    )
