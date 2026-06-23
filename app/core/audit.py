from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def log_audit(
    db: Session,
    *,
    action_code: str,
    action_label: str,
    entity_type: str,
    entity_id: str,
    actor: User | None = None,
    caisse_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        action_code=action_code,
        action_label=action_label,
        actor_id=actor.id if actor else None,
        actor_nom_snapshot=actor.nom if actor else "Systeme",
        actor_role_snapshot=actor.role if actor else "systeme",
        entity_type=entity_type,
        entity_id=entity_id,
        caisse_id=caisse_id if caisse_id is not None else getattr(actor, "caisse_id", None),
        detail_json=detail or None,
    )
    db.add(entry)
    db.flush()
    return entry
