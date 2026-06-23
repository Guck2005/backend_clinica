from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.alerting import sweep_business_alerts
from app.core.reporting import (
    build_alert_detailed_rows,
    build_mobile_money_audit_rows,
    build_payment_breakdown,
    build_summary_payload,
    load_alerts_for_period,
    load_audit_logs_for_period,
    load_transactions_for_period,
    load_visits_for_period,
    period_bounds,
    render_csv,
    render_pdf,
    render_xlsx,
)
from app.db.session import get_db
from app.models.user import User


router = APIRouter(prefix="/reports", tags=["reports"])


def get_anchor(anchor_date: str | None) -> date:
    return date.fromisoformat(anchor_date) if anchor_date else datetime.now().date()


def report_dataset(db: Session, period: str, anchor: date, caisse_id: int | None) -> dict:
    sweep_business_alerts(db)
    db.commit()
    transactions = load_transactions_for_period(db, period=period, anchor_date=anchor, caisse_id=caisse_id)
    visits = load_visits_for_period(db, period=period, anchor_date=anchor)
    alerts = load_alerts_for_period(db, period=period, anchor_date=anchor, caisse_id=caisse_id)
    audit_logs = load_audit_logs_for_period(db, period=period, anchor_date=anchor, caisse_id=caisse_id)
    start, end = period_bounds(period, anchor)
    return {
        "transactions": transactions,
        "visits": visits,
        "alerts": alerts,
        "audit_logs": audit_logs,
        "start_date": start.date(),
        "end_date": (end - timedelta(days=1)).date() if end > start else end.date(),
    }


@router.get("/summary", response_model=dict)
def get_summary_report(
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)
    totals = build_summary_payload(dataset["transactions"], dataset["visits"], dataset["alerts"])
    return {
        "period": period,
        "anchor_date": anchor.isoformat(),
        "caisse_id": None if consolidated else caisse_id,
        "consolidated": consolidated,
        "start_date": dataset["start_date"].isoformat(),
        "end_date": dataset["end_date"].isoformat(),
        "totals": totals,
        "conclusion": "Le total encaisse, les modes de paiement et le volume d'anomalies ont ete rapproches sur la periode selectionnee.",
    }


@router.get("/payment-breakdown", response_model=dict)
def get_payment_breakdown(
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)
    return {
        "period": period,
        "anchor_date": anchor.isoformat(),
        "caisse_id": None if consolidated else caisse_id,
        "items": build_payment_breakdown(dataset["transactions"]),
    }


@router.get("/visits-journal", response_model=dict)
def get_visits_journal(
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None)
    items = [
        {
            "id_visite": visit.id_visite,
            "patient_nom_complet": f"{visit.patient_nom} {visit.patient_prenom}".strip(),
            "patient_tel": visit.patient_tel,
            "motif_visite": visit.motif_visite,
            "service_oriente": visit.service_oriente,
            "statut": visit.statut,
            "created_at": visit.created_at.isoformat(),
            "agent_accueil_id": visit.agent_accueil_id,
        }
        for visit in dataset["visits"]
    ]
    return {"period": period, "anchor_date": anchor.isoformat(), "items": items}


@router.get("/mobile-money-audit", response_model=dict)
def get_mobile_money_audit(
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)
    return {
        "period": period,
        "anchor_date": anchor.isoformat(),
        "caisse_id": None if consolidated else caisse_id,
        "items": build_mobile_money_audit_rows(dataset["transactions"]),
    }


@router.get("/alerts-detailed", response_model=dict)
def get_alerts_detailed(
    period: str = Query(default="month", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)
    items = build_alert_detailed_rows(dataset["alerts"])
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "period": period,
        "anchor_date": anchor.isoformat(),
        "items": items,
        "total": len(items),
    }


@router.get("/audit-log", response_model=dict)
def get_audit_log_report(
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> dict:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)
    items = [
        {
            "id": log.id,
            "action_code": log.action_code,
            "action_label": log.action_label,
            "actor_nom": log.actor_nom_snapshot,
            "actor_role": log.actor_role_snapshot,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "caisse_id": log.caisse_id,
            "created_at": log.created_at.isoformat(),
        }
        for log in dataset["audit_logs"]
    ]
    return {"period": period, "anchor_date": anchor.isoformat(), "items": items, "total": len(items)}


@router.get("/export")
def export_report(
    report_type: str = Query(..., pattern="^(summary|payment-breakdown|visits-journal|mobile-money-audit|alerts-detailed|audit-log)$"),
    format: str = Query(..., pattern="^(pdf|csv|xlsx)$"),
    period: str = Query(default="day", pattern="^(day|week|month|year)$"),
    anchor_date: str | None = None,
    caisse_id: int | None = None,
    consolidated: bool = False,
    _: User = Depends(require_roles("superviseur", "admin", "auditeur")),
    db: Session = Depends(get_db),
) -> Response:
    anchor = get_anchor(anchor_date)
    dataset = report_dataset(db, period, anchor, None if consolidated else caisse_id)

    if report_type == "summary":
        rows = [build_summary_payload(dataset["transactions"], dataset["visits"], dataset["alerts"])]
        columns = [
            ("encaisse_fcfa", "Encaisse FCFA"),
            ("especes_fcfa", "Especes FCFA"),
            ("cheques_fcfa", "Cheques FCFA"),
            ("mobile_money_fcfa", "Mobile Money FCFA"),
            ("visits_total", "Dossiers"),
            ("alerts_total", "Anomalies"),
        ]
        title = "Synthese comptable et operationnelle"
        subtitle = "Constat consolide sur la periode selectionnee."
    elif report_type == "payment-breakdown":
        rows = build_payment_breakdown(dataset["transactions"])
        columns = [("moyen_paiement", "Mode"), ("statut", "Statut"), ("count", "Nombre"), ("total_fcfa", "Total FCFA")]
        title = "Ventilation des paiements"
        subtitle = "Repartition des encaissements par mode et statut."
    elif report_type == "visits-journal":
        rows = [
            {
                "id_visite": visit.id_visite,
                "patient_nom_complet": f"{visit.patient_nom} {visit.patient_prenom}".strip(),
                "patient_tel": visit.patient_tel,
                "motif_visite": visit.motif_visite,
                "service_oriente": visit.service_oriente,
                "statut": visit.statut,
                "created_at": visit.created_at.isoformat(),
            }
            for visit in dataset["visits"]
        ]
        columns = [
            ("id_visite", "Dossier"),
            ("patient_nom_complet", "Patient"),
            ("patient_tel", "Telephone"),
            ("motif_visite", "Motif"),
            ("service_oriente", "Service"),
            ("statut", "Statut"),
            ("created_at", "Date"),
        ]
        title = "Journal des visites"
        subtitle = "Suivi des dossiers de visite sur la periode selectionnee."
    elif report_type == "mobile-money-audit":
        rows = build_mobile_money_audit_rows(dataset["transactions"])
        columns = [
            ("id_visite", "Dossier"),
            ("transaction_id", "Transaction"),
            ("provider_attempt_id", "Tentative provider"),
            ("provider_status", "Statut provider"),
            ("reference_paiement", "Reference"),
            ("montant_attendu_fcfa", "Montant attendu"),
            ("montant_provider_fcfa", "Montant provider"),
            ("verdict", "Verdict"),
            ("observation", "Observation"),
        ]
        title = "Releve d'audit Mobile Money"
        subtitle = "Comparaison entre le systeme local et les etats FedaPay."
    elif report_type == "alerts-detailed":
        rows = build_alert_detailed_rows(dataset["alerts"])
        columns = [
            ("rule_name", "Anomalie"),
            ("gravite", "Gravite"),
            ("status", "Statut"),
            ("impact_amount_fcfa", "Impact FCFA"),
            ("constat", "Constat"),
            ("pieces_concernees", "Pieces concernees"),
            ("recommandation", "Recommandation"),
        ]
        title = "Rapport detaille des anomalies"
        subtitle = "Constat, impact et recommandation de traitement."
    else:
        rows = [
            {
                "id": log.id,
                "action_code": log.action_code,
                "action_label": log.action_label,
                "actor_nom": log.actor_nom_snapshot,
                "actor_role": log.actor_role_snapshot,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "caisse_id": log.caisse_id,
                "created_at": log.created_at.isoformat(),
            }
            for log in dataset["audit_logs"]
        ]
        columns = [
            ("id", "ID"),
            ("action_code", "Code action"),
            ("action_label", "Libelle"),
            ("actor_nom", "Acteur"),
            ("actor_role", "Role"),
            ("entity_type", "Entite"),
            ("entity_id", "Reference"),
            ("caisse_id", "Caisse"),
            ("created_at", "Date"),
        ]
        title = "Journal d'audit"
        subtitle = "Trace append-only des operations controlees."

    if format == "csv":
        content = render_csv(rows, [key for key, _ in columns])
        media_type = "text/csv; charset=utf-8"
    elif format == "xlsx":
        content = render_xlsx(report_type, rows, [key for key, _ in columns])
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = render_pdf(title, subtitle, rows, columns)
        media_type = "application/pdf"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{report_type}.{format}"'},
    )
