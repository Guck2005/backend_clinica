from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.alerting import resolve_alert, send_alert_email, sweep_business_alerts
from app.core.reporting import build_alert_detailed_rows, render_csv, render_pdf, render_xlsx
from app.db.session import get_db
from app.models.alert import Alert
from app.models.user import User
from app.schemas.alert import AlertListResponse, AlertRead, AlertResolveRequest


router = APIRouter(prefix="/alerts", tags=["alerts"])

LEGACY_RULE_ALIASES = {
    "A5": "CHEQUE_REJETE_APRES_FACTURE",
    "A6": "ECART_ESPECES_CAISSE",
    "A7": "ECART_VERSEMENT_BANCAIRE",
}


def alert_to_read(alert: Alert) -> AlertRead:
    return AlertRead(
        code=alert.code,
        rule_code=alert.rule_code,
        rule_name=alert.rule_name,
        gravite=alert.gravite,
        message=alert.message,
        caisse_id=alert.caisse_id,
        source_type=alert.source_type,
        source_id=alert.source_id,
        details=alert.details_json,
        impact_amount_fcfa=alert.impact_amount_fcfa,
        status=alert.status,
        first_detected_at=alert.first_detected_at,
        last_detected_at=alert.last_detected_at,
        resolved_at=alert.resolved_at,
        notification_email_status=alert.notification_email_status,
        notification_email_sent_at=alert.notification_email_sent_at,
        created_at=alert.created_at,
        active=alert.active,
    )


@router.get("", response_model=AlertListResponse)
def list_alerts(
    rule_code: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    gravite: str | None = None,
    caisse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    active: bool | None = None,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> AlertListResponse:
    sweep_business_alerts(db)
    db.commit()
    query = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
    if rule_code:
        normalized_rule_code = LEGACY_RULE_ALIASES.get(rule_code.strip().upper(), rule_code.strip())
        query = query.where(Alert.rule_code == normalized_rule_code)
    if status_filter:
        query = query.where(Alert.status == status_filter.upper().strip())
    if gravite:
        query = query.where(Alert.gravite == gravite.strip())
    if caisse_id is not None:
        query = query.where(Alert.caisse_id == caisse_id)
    if date_from is not None:
        query = query.where(Alert.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        query = query.where(Alert.created_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if active is not None:
        query = query.where(Alert.active.is_(active))
    items = db.scalars(query).all()
    return AlertListResponse(items=[alert_to_read(item) for item in items], total=len(items))


@router.get("/report/detailed", response_model=dict)
def get_detailed_alert_report(
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    sweep_business_alerts(db)
    db.commit()
    alerts = db.scalars(select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())).all()
    rows = build_alert_detailed_rows(alerts)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "items": rows,
        "total": len(rows),
    }


@router.get("/report/export")
def export_alert_report(
    format: str = Query(..., pattern="^(pdf|csv|xlsx)$"),
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> Response:
    sweep_business_alerts(db)
    db.commit()
    alerts = db.scalars(select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())).all()
    rows = build_alert_detailed_rows(alerts)
    columns = [
        ("rule_name", "Anomalie"),
        ("gravite", "Gravite"),
        ("status", "Statut"),
        ("caisse_id", "Caisse"),
        ("impact_amount_fcfa", "Impact FCFA"),
        ("constat", "Constat"),
        ("pieces_concernees", "Pieces concernees"),
        ("recommandation", "Recommandation"),
    ]
    if format == "csv":
        content = render_csv(rows, [key for key, _ in columns])
        media_type = "text/csv; charset=utf-8"
    elif format == "xlsx":
        content = render_xlsx("alertes", rows, [key for key, _ in columns])
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = render_pdf(
            "Rapport detaille des anomalies",
            "Constats de controle interne et recommandations de traitement.",
            rows,
            columns,
        )
        media_type = "application/pdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="alertes-detail.{format}"'},
    )


@router.get("/{alert_code}", response_model=AlertRead)
def get_alert(
    alert_code: str,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> AlertRead:
    sweep_business_alerts(db)
    db.commit()
    alert = db.scalar(select(Alert).where(Alert.code == alert_code.strip().upper()))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerte introuvable.")
    return alert_to_read(alert)


@router.patch("/{alert_code}/resolve", response_model=AlertRead)
def resolve_alert_route(
    alert_code: str,
    payload: AlertResolveRequest,
    user: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> AlertRead:
    alert = db.scalar(select(Alert).where(Alert.code == alert_code.strip().upper()))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerte introuvable.")
    resolve_alert(db, alert=alert, actor=user, resolution_note=payload.resolution_note)
    db.commit()
    db.refresh(alert)
    return alert_to_read(alert)


@router.post("/{alert_code}/send-email", response_model=AlertRead)
def send_alert_email_route(
    alert_code: str,
    user: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> AlertRead:
    alert = db.scalar(select(Alert).where(Alert.code == alert_code.strip().upper()))
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerte introuvable.")
    send_alert_email(db, alert=alert, actor=user)
    db.commit()
    db.refresh(alert)
    return alert_to_read(alert)
