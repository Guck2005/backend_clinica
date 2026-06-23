from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_hex
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit
from app.core.config import settings
from app.integrations.brevo_email import EmailProviderError, get_email_provider
from app.integrations.fedapay import extract_amount_debited
from app.models.alert import Alert
from app.models.invoice import Invoice
from app.models.transaction import Payment, Transaction, TransactionLine
from app.models.user import User
from app.models.visit import Visit


AlertSeverity = str
AlertRuleCode = str


ALERT_RULES: dict[AlertRuleCode, dict[str, str]] = {
    "MOMO_MONTANT_INCOHERENT": {
        "rule_name": "Montant Mobile Money incoherent",
        "gravite": "haute",
    },
    "MOMO_CONFIRME_SANS_FACTURE": {
        "rule_name": "Paiement Mobile Money confirme sans facture coherente",
        "gravite": "critique",
    },
    "FACTURE_PAYEE_SANS_CONFIRMATION": {
        "rule_name": "Facture finalisee sans confirmation de paiement",
        "gravite": "critique",
    },
    "FACTURE_TENTEE_SANS_PAIEMENT_CONFIRME": {
        "rule_name": "Tentative de facture sans paiement confirme",
        "gravite": "haute",
    },
    "CHEQUE_REJETE_APRES_FACTURE": {
        "rule_name": "Cheque rejete apres emission de facture",
        "gravite": "critique",
    },
    "ECART_ESPECES_CAISSE": {
        "rule_name": "Ecart d'especes en caisse",
        "gravite": "haute",
    },
    "ECART_VERSEMENT_BANCAIRE": {
        "rule_name": "Ecart de versement bancaire",
        "gravite": "critique",
    },
    "LIGNE_NON_HONOREE_SANS_MOTIF": {
        "rule_name": "Ligne non honoree sans motif",
        "gravite": "moyenne",
    },
    "PAIEMENTS_MULTIPLES_MEME_FACTURE": {
        "rule_name": "Paiements multiples sur une meme facture",
        "gravite": "critique",
    },
    "DOSSIER_SANS_PASSAGE_CAISSE_4H": {
        "rule_name": "Dossier sans passage caisse apres quatre heures",
        "gravite": "haute",
    },
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def alert_rule_meta(rule_code: str) -> dict[str, str]:
    if rule_code not in ALERT_RULES:
        raise ValueError(f"Unknown alert rule: {rule_code}")
    return ALERT_RULES[rule_code]


def generate_alert_occurrence_code() -> str:
    return f"ALT-{token_hex(5).upper()}"


def alert_dedupe_query(
    *,
    rule_code: str,
    source_type: str,
    source_id: str,
):
    return select(Alert).where(
        Alert.rule_code == rule_code,
        Alert.source_type == source_type,
        Alert.source_id == source_id,
        Alert.status == "ACTIVE",
    )


def upsert_named_alert(
    db: Session,
    *,
    rule_code: str,
    message: str,
    source_type: str,
    source_id: str,
    caisse_id: int | None,
    details: dict[str, Any] | None = None,
    impact_amount_fcfa: int | None = None,
    gravite: AlertSeverity | None = None,
    actor: User | None = None,
    auto_notify: bool = True,
) -> tuple[Alert, bool]:
    meta = alert_rule_meta(rule_code)
    alert = db.scalar(
        alert_dedupe_query(rule_code=rule_code, source_type=source_type, source_id=source_id)
    )
    created = False
    now = utcnow()
    severity = gravite or meta["gravite"]

    if alert is None:
        created = True
        alert = Alert(
            code=generate_alert_occurrence_code(),
            rule_code=rule_code,
            rule_name=meta["rule_name"],
            gravite=severity,
            message=message,
            caisse_id=caisse_id,
            source_type=source_type,
            source_id=source_id,
            active=True,
            status="ACTIVE",
            details_json=details or None,
            impact_amount_fcfa=impact_amount_fcfa,
            first_detected_at=now,
            last_detected_at=now,
        )
        db.add(alert)
        db.flush()
        log_audit(
            db,
            action_code="ALERT_CREATED",
            action_label=f"Alerte creee - {alert.rule_name}",
            entity_type="ALERT",
            entity_id=alert.code,
            actor=actor,
            caisse_id=caisse_id,
            detail={
                "rule_code": rule_code,
                "message": message,
                "impact_amount_fcfa": impact_amount_fcfa,
                "source_type": source_type,
                "source_id": source_id,
            },
        )
    else:
        alert.rule_name = meta["rule_name"]
        alert.gravite = severity
        alert.message = message
        alert.caisse_id = caisse_id
        alert.details_json = details or None
        alert.impact_amount_fcfa = impact_amount_fcfa
        alert.last_detected_at = now
        alert.active = True
        alert.status = "ACTIVE"

    if created and auto_notify and severity in {"haute", "critique"}:
        send_alert_email(db, alert=alert, actor=actor)

    return alert, created


def resolve_alert(
    db: Session,
    *,
    alert: Alert,
    actor: User | None = None,
    resolution_note: str | None = None,
) -> Alert:
    if alert.status == "RESOLUE":
        return alert

    alert.active = False
    alert.status = "RESOLUE"
    alert.resolved_at = utcnow()
    details = dict(alert.details_json or {})
    if resolution_note:
        details["resolution_note"] = resolution_note.strip()
        alert.details_json = details
    db.flush()
    log_audit(
        db,
        action_code="ALERT_RESOLVED",
        action_label=f"Alerte resolue - {alert.rule_name}",
        entity_type="ALERT",
        entity_id=alert.code,
        actor=actor,
        caisse_id=alert.caisse_id,
        detail={"resolution_note": resolution_note},
    )
    return alert


def _build_alert_email_text(alert: Alert) -> str:
    impact = f"{alert.impact_amount_fcfa} FCFA" if alert.impact_amount_fcfa is not None else "Non chiffre"
    source = f"{alert.source_type} {alert.source_id}"
    caisse = str(alert.caisse_id) if alert.caisse_id is not None else "Consolide / non rattache"
    return "\n".join(
        [
            f"Alerte de supervision: {alert.rule_name}",
            f"Gravite: {alert.gravite}",
            f"Date: {alert.first_detected_at.isoformat() if alert.first_detected_at else ''}",
            f"Caisse: {caisse}",
            f"Source: {source}",
            f"Impact financier: {impact}",
            f"Constat: {alert.message}",
            "Action recommandee: verifier immediatement la piece source et documenter la resolution.",
        ]
    )


def _build_alert_email_html(alert: Alert) -> str:
    impact = f"{alert.impact_amount_fcfa} FCFA" if alert.impact_amount_fcfa is not None else "Non chiffre"
    caisse = str(alert.caisse_id) if alert.caisse_id is not None else "Consolide / non rattache"
    return (
        "<html><body>"
        "<h2>Alerte de supervision</h2>"
        f"<p><strong>Anomalie</strong> : {alert.rule_name}</p>"
        f"<p><strong>Gravite</strong> : {alert.gravite}</p>"
        f"<p><strong>Date</strong> : {alert.first_detected_at.isoformat() if alert.first_detected_at else ''}</p>"
        f"<p><strong>Caisse</strong> : {caisse}</p>"
        f"<p><strong>Source</strong> : {alert.source_type} {alert.source_id}</p>"
        f"<p><strong>Impact financier</strong> : {impact}</p>"
        f"<p><strong>Constat</strong> : {alert.message}</p>"
        "<p><strong>Action recommandee</strong> : verifier immediatement la piece source et documenter la resolution.</p>"
        "</body></html>"
    )


def send_alert_email(
    db: Session,
    *,
    alert: Alert,
    actor: User | None = None,
) -> Alert:
    subject = f"[CaisseTrace] {alert.rule_name}"
    recipient = settings.brevo_alert_email_to
    provider = get_email_provider()

    if not recipient:
        alert.notification_email_status = "LOCAL_LOG"
        alert.notification_email_sent_at = utcnow()
        log_audit(
            db,
            action_code="ALERT_EMAIL_LOGGED",
            action_label=f"Notification d'alerte journalisee - {alert.rule_name}",
            entity_type="ALERT",
            entity_id=alert.code,
            actor=actor,
            caisse_id=alert.caisse_id,
            detail={"status": "LOCAL_LOG"},
        )
        return alert

    try:
        result = provider.send_email(
            recipient=recipient,
            subject=subject,
            html_content=_build_alert_email_html(alert),
            text_content=_build_alert_email_text(alert),
        )
    except EmailProviderError as exc:
        alert.notification_email_status = "ECHEC"
        alert.notification_email_sent_at = None
        details = dict(alert.details_json or {})
        details["notification_email_error"] = exc.message[:255]
        alert.details_json = details
        return alert

    alert.notification_email_status = result.status
    alert.notification_email_sent_at = utcnow()
    log_audit(
        db,
        action_code="ALERT_EMAIL_SENT",
        action_label=f"Notification d'alerte envoyee - {alert.rule_name}",
        entity_type="ALERT",
        entity_id=alert.code,
        actor=actor,
        caisse_id=alert.caisse_id,
        detail={"provider": result.provider, "message_id": result.message_id},
    )
    return alert


def _resolve_swept_alerts(
    db: Session,
    *,
    rule_code: str,
    active_sources: set[tuple[str, str]],
) -> None:
    active_alerts = db.scalars(
        select(Alert).where(Alert.rule_code == rule_code, Alert.status == "ACTIVE")
    ).all()
    for alert in active_alerts:
        key = (alert.source_type, alert.source_id)
        if key not in active_sources:
            resolve_alert(db, alert=alert, actor=None, resolution_note="Anomalie non reproduite au sweep de coherence.")


def sweep_business_alerts(db: Session) -> None:
    now = utcnow()

    a1_active: set[tuple[str, str]] = set()
    momo_payments = db.scalars(
        select(Payment)
        .where(Payment.moyen_paiement == "MOBILE_MONEY")
        .options(selectinload(Payment.transaction).selectinload(Transaction.invoice))
    ).all()
    for payment in momo_payments:
        provider_amount = extract_amount_debited(payment.raw_payload)
        if payment.statut == "CONFIRME" and provider_amount is not None and provider_amount != payment.montant_fcfa:
            source_key = ("PAYMENT", str(payment.id))
            a1_active.add(source_key)
            upsert_named_alert(
                db,
                rule_code="MOMO_MONTANT_INCOHERENT",
                message=(
                    f"Le paiement Mobile Money {payment.id} presente un montant attendu de "
                    f"{payment.montant_fcfa} FCFA pour un montant provider de {provider_amount} FCFA."
                ),
                source_type="PAYMENT",
                source_id=str(payment.id),
                caisse_id=payment.transaction.caisse_id if payment.transaction else None,
                impact_amount_fcfa=provider_amount - payment.montant_fcfa,
                details={
                    "montant_attendu_fcfa": payment.montant_fcfa,
                    "montant_provider_fcfa": provider_amount,
                },
                auto_notify=True,
            )
    _resolve_swept_alerts(db, rule_code="MOMO_MONTANT_INCOHERENT", active_sources=a1_active)

    a2_active: set[tuple[str, str]] = set()
    payments_with_transactions = db.scalars(
        select(Payment)
        .where(Payment.moyen_paiement == "MOBILE_MONEY")
        .options(
            selectinload(Payment.transaction).selectinload(Transaction.invoice),
            selectinload(Payment.transaction).selectinload(Transaction.visit),
        )
    ).all()
    for payment in payments_with_transactions:
        transaction = payment.transaction
        if transaction is None:
            continue
        provider_status = (payment.provider_status or "").lower()
        if provider_status == "approved" and (payment.statut != "CONFIRME" or transaction.invoice is None):
            source_key = ("TRANSACTION", str(transaction.id))
            a2_active.add(source_key)
            upsert_named_alert(
                db,
                rule_code="MOMO_CONFIRME_SANS_FACTURE",
                message=(
                    f"La transaction {transaction.id} est approuvee cote provider, mais la facture ou la "
                    "confirmation locale reste incoherente."
                ),
                source_type="TRANSACTION",
                source_id=str(transaction.id),
                caisse_id=transaction.caisse_id,
                impact_amount_fcfa=transaction.montant_encaisse_fcfa,
                details={"provider_status": provider_status, "payment_status": payment.statut},
            )
    _resolve_swept_alerts(db, rule_code="MOMO_CONFIRME_SANS_FACTURE", active_sources=a2_active)

    a3_active: set[tuple[str, str]] = set()
    invoices = db.scalars(
        select(Invoice)
        .options(
            selectinload(Invoice.transaction).selectinload(Transaction.payments),
        )
    ).all()
    for invoice in invoices:
        payment = invoice.transaction.latest_payment if invoice.transaction else None
        if payment is None:
            continue
        payment_ok = (
            (payment.moyen_paiement == "ESPECES" and payment.statut == "CONFIRME")
            or (payment.moyen_paiement == "MOBILE_MONEY" and payment.statut == "CONFIRME")
            or (payment.moyen_paiement == "CHEQUE" and payment.statut in {"RECU", "ENCAISSE"})
        )
        if invoice.statut_document in {"EMISE", "EN_ATTENTE_CONFIRMATION_BANCAIRE"} and not payment_ok:
            source_key = ("INVOICE", invoice.numero_facture)
            a3_active.add(source_key)
            upsert_named_alert(
                db,
                rule_code="FACTURE_PAYEE_SANS_CONFIRMATION",
                message=(
                    f"La facture {invoice.numero_facture} est finalisee alors que le paiement "
                    f"associe reste au statut {payment.statut}."
                ),
                source_type="INVOICE",
                source_id=invoice.numero_facture,
                caisse_id=invoice.transaction.caisse_id if invoice.transaction else None,
                impact_amount_fcfa=payment.montant_fcfa,
                details={"payment_status": payment.statut, "payment_method": payment.moyen_paiement},
            )
    _resolve_swept_alerts(db, rule_code="FACTURE_PAYEE_SANS_CONFIRMATION", active_sources=a3_active)

    a4_active: set[tuple[str, str]] = set()
    for invoice in invoices:
        payment = invoice.transaction.latest_payment if invoice.transaction else None
        if payment is None:
            continue
        if payment.statut in {"EN_ATTENTE", "ECHOUE"}:
            source_key = ("INVOICE", invoice.numero_facture)
            a4_active.add(source_key)
            upsert_named_alert(
                db,
                rule_code="FACTURE_TENTEE_SANS_PAIEMENT_CONFIRME",
                message=(
                    f"Une facture ou pre-facture {invoice.numero_facture} existe alors que le paiement "
                    f"n'est pas confirme ({payment.statut})."
                ),
                source_type="INVOICE",
                source_id=invoice.numero_facture,
                caisse_id=invoice.transaction.caisse_id if invoice.transaction else None,
                impact_amount_fcfa=payment.montant_fcfa,
                details={"payment_status": payment.statut},
            )
    _resolve_swept_alerts(db, rule_code="FACTURE_TENTEE_SANS_PAIEMENT_CONFIRME", active_sources=a4_active)

    a8_active: set[tuple[str, str]] = set()
    invalid_lines = db.scalars(
        select(TransactionLine)
        .where(
            TransactionLine.payable.is_(False),
            or_(TransactionLine.motif_non_honore.is_(None), func.trim(TransactionLine.motif_non_honore) == ""),
        )
        .options(selectinload(TransactionLine.transaction))
    ).all()
    for line in invalid_lines:
        transaction = line.transaction
        if transaction is None:
            continue
        source_key = ("TRANSACTION_LINE", str(line.id))
        a8_active.add(source_key)
        upsert_named_alert(
            db,
            rule_code="LIGNE_NON_HONOREE_SANS_MOTIF",
            message=f"La ligne {line.id} de la transaction {transaction.id} est non honoree sans motif documente.",
            source_type="TRANSACTION_LINE",
            source_id=str(line.id),
            caisse_id=transaction.caisse_id,
            impact_amount_fcfa=line.montant_ligne_fcfa,
            details={"transaction_id": transaction.id},
        )
    _resolve_swept_alerts(db, rule_code="LIGNE_NON_HONOREE_SANS_MOTIF", active_sources=a8_active)

    a9_active: set[tuple[str, str]] = set()
    all_transactions = db.scalars(
        select(Transaction).options(selectinload(Transaction.payments))
    ).all()
    for transaction in all_transactions:
        finalised_count = sum(
            1
            for payment in transaction.payments
            if (
                (payment.moyen_paiement == "ESPECES" and payment.statut == "CONFIRME")
                or (payment.moyen_paiement == "MOBILE_MONEY" and payment.statut == "CONFIRME")
                or (payment.moyen_paiement == "CHEQUE" and payment.statut in {"RECU", "ENCAISSE"})
            )
        )
        if finalised_count > 1:
            source_key = ("TRANSACTION", str(transaction.id))
            a9_active.add(source_key)
            upsert_named_alert(
                db,
                rule_code="PAIEMENTS_MULTIPLES_MEME_FACTURE",
                message=(
                    f"La transaction {transaction.id} cumule {finalised_count} paiements finalises "
                    "pour une meme facture ou visite."
                ),
                source_type="TRANSACTION",
                source_id=str(transaction.id),
                caisse_id=transaction.caisse_id,
                impact_amount_fcfa=transaction.montant_encaisse_fcfa,
                details={"finalised_count": finalised_count},
            )
    _resolve_swept_alerts(db, rule_code="PAIEMENTS_MULTIPLES_MEME_FACTURE", active_sources=a9_active)

    a10_active: set[tuple[str, str]] = set()
    overdue_visits = db.scalars(
        select(Visit).where(
            Visit.statut == "EN_ATTENTE",
            Visit.created_at <= now - timedelta(hours=4),
        )
    ).all()
    for visit in overdue_visits:
        if visit.id_visite is None:
            continue
        source_key = ("VISIT", visit.id_visite)
        a10_active.add(source_key)
        upsert_named_alert(
            db,
            rule_code="DOSSIER_SANS_PASSAGE_CAISSE_4H",
            message=(
                f"Le dossier {visit.id_visite} n'a pas encore atteint la caisse plus de quatre heures "
                "apres son enregistrement a l'accueil."
            ),
            source_type="VISIT",
            source_id=visit.id_visite,
            caisse_id=None,
            details={"created_at": visit.created_at.isoformat()},
        )
    _resolve_swept_alerts(db, rule_code="DOSSIER_SANS_PASSAGE_CAISSE_4H", active_sources=a10_active)

