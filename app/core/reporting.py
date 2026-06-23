from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO, StringIO
import csv

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.alert import Alert
from app.models.audit_log import AuditLog
from app.models.invoice import Invoice
from app.models.transaction import Payment, Transaction
from app.models.visit import Visit


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def period_bounds(period: str, anchor_date: date) -> tuple[datetime, datetime]:
    start_day = datetime.combine(anchor_date, time.min, tzinfo=timezone.utc)
    if period == "day":
        return start_day, start_day + timedelta(days=1)
    if period == "week":
        start = start_day - timedelta(days=anchor_date.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = start_day.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    if period == "year":
        start = start_day.replace(month=1, day=1)
        return start, start.replace(year=start.year + 1)
    raise ValueError("Periode invalide")


def load_transactions_for_period(
    db: Session,
    *,
    period: str,
    anchor_date: date,
    caisse_id: int | None,
) -> list[Transaction]:
    start, end = period_bounds(period, anchor_date)
    query = (
        select(Transaction)
        .where(Transaction.created_at >= start, Transaction.created_at < end)
        .options(
            selectinload(Transaction.visit),
            selectinload(Transaction.caisse),
            selectinload(Transaction.payments),
            selectinload(Transaction.invoice),
        )
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
    )
    if caisse_id is not None:
        query = query.where(Transaction.caisse_id == caisse_id)
    return db.scalars(query).all()


def load_visits_for_period(
    db: Session,
    *,
    period: str,
    anchor_date: date,
) -> list[Visit]:
    start, end = period_bounds(period, anchor_date)
    return db.scalars(
        select(Visit)
        .where(Visit.created_at >= start, Visit.created_at < end)
        .order_by(Visit.created_at.asc(), Visit.id.asc())
    ).all()


def load_alerts_for_period(
    db: Session,
    *,
    period: str,
    anchor_date: date,
    caisse_id: int | None,
) -> list[Alert]:
    start, end = period_bounds(period, anchor_date)
    query = select(Alert).where(Alert.created_at >= start, Alert.created_at < end).order_by(Alert.created_at.desc())
    if caisse_id is not None:
        query = query.where(Alert.caisse_id == caisse_id)
    return db.scalars(query).all()


def load_audit_logs_for_period(
    db: Session,
    *,
    period: str,
    anchor_date: date,
    caisse_id: int | None,
) -> list[AuditLog]:
    start, end = period_bounds(period, anchor_date)
    query = select(AuditLog).where(AuditLog.created_at >= start, AuditLog.created_at < end).order_by(AuditLog.created_at.desc())
    if caisse_id is not None:
        query = query.where(AuditLog.caisse_id == caisse_id)
    return db.scalars(query).all()


def payment_counts_for_summary(transaction: Transaction) -> bool:
    payment = transaction.latest_payment
    if payment is None:
        return False
    if payment.moyen_paiement == "ESPECES":
        return payment.statut == "CONFIRME"
    if payment.moyen_paiement == "CHEQUE":
        return payment.statut in {"RECU", "ENCAISSE"}
    if payment.moyen_paiement == "MOBILE_MONEY":
        return payment.statut == "CONFIRME"
    return False


def build_summary_payload(transactions: list[Transaction], visits: list[Visit], alerts: list[Alert]) -> dict:
    totals = {
        "encaisse_fcfa": 0,
        "especes_fcfa": 0,
        "cheques_fcfa": 0,
        "mobile_money_fcfa": 0,
        "visits_total": len(visits),
        "alerts_total": len(alerts),
    }
    for transaction in transactions:
        payment = transaction.latest_payment
        if payment is None or not payment_counts_for_summary(transaction):
            continue
        totals["encaisse_fcfa"] += transaction.montant_encaisse_fcfa
        if payment.moyen_paiement == "ESPECES":
            totals["especes_fcfa"] += transaction.montant_encaisse_fcfa
        elif payment.moyen_paiement == "CHEQUE":
            totals["cheques_fcfa"] += transaction.montant_encaisse_fcfa
        elif payment.moyen_paiement == "MOBILE_MONEY":
            totals["mobile_money_fcfa"] += transaction.montant_encaisse_fcfa

    return totals


def build_payment_breakdown(transactions: list[Transaction]) -> list[dict]:
    grouped: dict[tuple[str, str], dict[str, int | str]] = {}
    for transaction in transactions:
        payment = transaction.latest_payment
        if payment is None:
            continue
        key = (payment.moyen_paiement, payment.statut)
        if key not in grouped:
            grouped[key] = {
                "moyen_paiement": payment.moyen_paiement,
                "statut": payment.statut,
                "total_fcfa": 0,
                "count": 0,
            }
        grouped[key]["total_fcfa"] = int(grouped[key]["total_fcfa"]) + transaction.montant_encaisse_fcfa
        grouped[key]["count"] = int(grouped[key]["count"]) + 1
    return list(grouped.values())


def build_mobile_money_audit_rows(transactions: list[Transaction]) -> list[dict]:
    rows: list[dict] = []
    for transaction in transactions:
        payment = transaction.latest_payment
        if payment is None or payment.moyen_paiement != "MOBILE_MONEY":
            continue
        provider_amount = None
        if isinstance(payment.raw_payload, dict):
            payload = payment.raw_payload
            provider_amount = payload.get("amount_debited") or payload.get("amount")
            try:
                provider_amount = int(provider_amount) if provider_amount is not None else None
            except (TypeError, ValueError):
                provider_amount = None
        verdict = "coherent"
        observation = "Aucun ecart significatif constate."
        if payment.provider_status == "queued_offline":
            verdict = "en_attente_reseau"
            observation = "Tentative non transmise au provider au moment du controle."
        elif payment.provider_status == "approved" and provider_amount is not None and provider_amount != payment.montant_fcfa:
            verdict = "incoherent"
            observation = "Le montant debite provider differe du montant local attendu."
        elif payment.provider_status in {"declined", "canceled", "expired"}:
            verdict = "echec_provider"
            observation = "Le provider signale un refus ou une annulation."

        rows.append(
            {
                "id_visite": transaction.visit.id_visite or "",
                "transaction_id": transaction.id,
                "numero_facture": transaction.invoice.numero_facture if transaction.invoice else None,
                "provider_attempt_id": payment.provider_attempt_id,
                "provider_status": payment.provider_status,
                "reference_paiement": payment.reference_paiement,
                "montant_attendu_fcfa": transaction.montant_encaisse_fcfa,
                "montant_provider_fcfa": provider_amount,
                "frais_provider_fcfa": None,
                "verdict": verdict,
                "observation": observation,
                "created_at": transaction.created_at,
            }
        )
    return rows


def build_alert_detailed_rows(alerts: list[Alert]) -> list[dict]:
    rows: list[dict] = []
    for alert in alerts:
        details = alert.details_json or {}
        rows.append(
            {
                "code": alert.code,
                "rule_name": alert.rule_name,
                "gravite": alert.gravite,
                "status": alert.status,
                "caisse_id": alert.caisse_id,
                "impact_amount_fcfa": alert.impact_amount_fcfa,
                "constat": alert.message,
                "perimetre": details.get("perimetre") or f"Source {alert.source_type} {alert.source_id}",
                "ecarts_observes": details.get("ecarts_observes") or alert.message,
                "pieces_concernees": details.get("pieces_concernees") or f"{alert.source_type} {alert.source_id}",
                "conclusion": details.get("conclusion") or "Une verification contradictoire est recommandee.",
                "recommandation": details.get("recommandation") or "Analyser la piece source, valider les justificatifs et tracer la resolution.",
                "created_at": alert.created_at,
                "last_detected_at": alert.last_detected_at,
            }
        )
    return rows


def render_csv(rows: list[dict], field_order: list[str]) -> bytes:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_order)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in field_order})
    return buffer.getvalue().encode("utf-8")


def render_xlsx(sheet_name: str, rows: list[dict], field_order: list[str]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name[:31]
    sheet.append(field_order)
    for row in rows:
        sheet.append([row.get(field) for field in field_order])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def render_pdf(title: str, subtitle: str, rows: list[dict], columns: list[tuple[str, str]]) -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    title_style.fontName = "Helvetica-Bold"
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12)

    data = [[label for _, label in columns]]
    for row in rows:
        data.append([str(row.get(key, "")) for key, _ in columns])

    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#444444")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEADING", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    story = [
        Paragraph(title, title_style),
        Spacer(1, 6),
        Paragraph(subtitle, subtitle_style),
        Spacer(1, 12),
        table,
    ]
    doc.build(story)
    return output.getvalue()
