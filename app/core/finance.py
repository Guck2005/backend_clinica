from __future__ import annotations

from datetime import datetime, timezone
from secrets import token_urlsafe

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.phone import normalize_phone
from app.integrations.brevo_sms import SmsProviderError, get_sms_provider
from app.integrations.fedapay import extract_error_code
from app.models.alert import Alert
from app.models.invoice import Invoice
from app.models.transaction import Payment, Transaction


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def patient_full_name(transaction: Transaction) -> str:
    return f"{transaction.visit.patient_nom} {transaction.visit.patient_prenom}".strip()


def build_invoice_number(invoice_id: int) -> str:
    return f"FA-229-{invoice_id:06d}"


def payment_reference_snapshot(payment: Payment) -> str | None:
    if payment.moyen_paiement == "MOBILE_MONEY":
        return payment.reference_paiement
    if payment.moyen_paiement == "CHEQUE":
        return payment.cheque_numero
    return None


def generate_invoice_public_token() -> str:
    return token_urlsafe(24)


def build_invoice_download_url(invoice: Invoice) -> str:
    return f"{settings.public_app_url}/factures/{invoice.numero_facture}/pdf"


def build_invoice_public_download_url(invoice: Invoice) -> str:
    return f"{settings.public_app_url}/public/factures/{invoice.public_token}.pdf"


def payment_document_state(payment: Payment) -> tuple[str, str | None] | None:
    if payment.moyen_paiement == "ESPECES" and payment.statut == "CONFIRME":
        return "EMISE", "Paiement en especes confirme."
    if payment.moyen_paiement == "MOBILE_MONEY" and payment.statut == "CONFIRME":
        return "EMISE", "Paiement Mobile Money confirme."
    if payment.moyen_paiement == "CHEQUE":
        cheque_numero = payment.cheque_numero or "inconnu"
        if payment.statut == "RECU":
            return (
                "EN_ATTENTE_CONFIRMATION_BANCAIRE",
                f"Paiement par cheque n° {cheque_numero} - en attente de confirmation bancaire",
            )
        if payment.statut == "ENCAISSE":
            return "EMISE", f"Paiement par cheque n° {cheque_numero} confirme par la banque"
        if payment.statut == "REJETE":
            return "CHEQUE_REJETE", f"Cheque n° {cheque_numero} rejete par la banque"
    return None


def upsert_invoice_for_transaction(db: Session, transaction: Transaction) -> Invoice | None:
    if transaction.id is None:
        db.flush()

    payment = transaction.latest_payment
    if payment is None or transaction.visit.id_visite is None:
        return None

    state = payment_document_state(payment)
    invoice = db.scalar(select(Invoice).where(Invoice.transaction_id == transaction.id))
    if state is None:
        return invoice

    statut_document, mention_paiement = state
    if invoice is None:
        invoice = Invoice(
            numero_facture="PENDING",
            transaction_id=transaction.id,
            id_visite_snapshot=transaction.visit.id_visite,
            patient_nom_snapshot=patient_full_name(transaction),
            patient_tel_snapshot=transaction.visit.patient_tel,
            moyen_paiement_snapshot=payment.moyen_paiement,
            reference_snapshot=payment_reference_snapshot(payment),
            statut_document=statut_document,
            mention_paiement=mention_paiement,
            public_token=generate_invoice_public_token(),
            sms_status="A_ENVOYER",
        )
        db.add(invoice)
        db.flush()
        invoice.numero_facture = build_invoice_number(invoice.id)
    else:
        invoice.id_visite_snapshot = transaction.visit.id_visite
        invoice.patient_nom_snapshot = patient_full_name(transaction)
        invoice.patient_tel_snapshot = transaction.visit.patient_tel
        invoice.moyen_paiement_snapshot = payment.moyen_paiement
        invoice.reference_snapshot = payment_reference_snapshot(payment)
        invoice.statut_document = statut_document
        invoice.mention_paiement = mention_paiement
        if not invoice.public_token:
            invoice.public_token = generate_invoice_public_token()
        if not invoice.sms_status:
            invoice.sms_status = "A_ENVOYER"

    return invoice


def should_auto_send_invoice_sms(invoice: Invoice, transaction: Transaction) -> bool:
    payment = transaction.latest_payment
    if payment is None:
        return False
    if invoice.statut_document == "CHEQUE_REJETE":
        return False
    if payment.moyen_paiement == "ESPECES" and payment.statut == "CONFIRME":
        return True
    if payment.moyen_paiement == "MOBILE_MONEY" and payment.statut == "CONFIRME":
        return True
    if payment.moyen_paiement == "CHEQUE" and payment.statut == "RECU":
        return True
    return False


def build_invoice_sms_message(invoice: Invoice) -> str:
    parts = [
        f"Hopital Saint Jean - facture {invoice.numero_facture}",
        f"dossier {invoice.id_visite_snapshot}",
    ]
    if invoice.statut_document == "EN_ATTENTE_CONFIRMATION_BANCAIRE":
        parts.append("cheque en attente de confirmation bancaire")
    elif invoice.statut_document == "CHEQUE_REJETE":
        parts.append("cheque rejete")
    parts.append(build_invoice_public_download_url(invoice))
    return ". ".join(parts)


def deliver_invoice_sms(
    db: Session,
    invoice: Invoice,
    *,
    force: bool = False,
) -> Invoice:
    transaction = invoice.transaction
    if transaction is None:
        return invoice

    if not force:
        if not should_auto_send_invoice_sms(invoice, transaction):
            return invoice
        if invoice.sms_status in {"ENVOYE", "LOCAL_LOG"}:
            return invoice

    recipient = normalize_phone(invoice.patient_tel_snapshot)
    if not recipient:
        invoice.sms_status = "ECHEC"
        invoice.sms_provider = "BREVO" if settings.brevo_api_key and settings.brevo_sms_sender else "LOCAL_LOG"
        invoice.sms_message_id = None
        invoice.sms_error = "Numero patient invalide pour l'envoi SMS."
        invoice.sms_sent_at = None
        return invoice

    provider = get_sms_provider()
    try:
        result = provider.send_sms(recipient=recipient, content=build_invoice_sms_message(invoice))
    except SmsProviderError as exc:
        invoice.sms_status = "ECHEC"
        invoice.sms_provider = "BREVO"
        invoice.sms_message_id = None
        invoice.sms_error = exc.message[:255]
        invoice.sms_sent_at = None
        return invoice

    invoice.sms_status = result.status
    invoice.sms_provider = result.provider
    invoice.sms_message_id = result.message_id
    invoice.sms_error = None
    invoice.sms_sent_at = utcnow()
    db.flush()
    return invoice


def create_alert_once(
    db: Session,
    *,
    code: str,
    rule_code: str,
    gravite: str,
    message: str,
    caisse_id: int | None,
    source_type: str,
    source_id: str,
) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.code == code))
    if alert is None:
        alert = Alert(
            code=code,
            rule_code=rule_code,
            gravite=gravite,
            message=message,
            caisse_id=caisse_id,
            source_type=source_type,
            source_id=source_id,
            active=True,
        )
        db.add(alert)
        db.flush()
        return alert

    alert.rule_code = rule_code
    alert.gravite = gravite
    alert.message = message
    alert.caisse_id = caisse_id
    alert.source_type = source_type
    alert.source_id = source_id
    alert.active = True
    return alert


def transaction_blocking_reason(transaction: Transaction) -> str | None:
    payment = transaction.latest_payment
    if payment is None:
        return None

    if payment.moyen_paiement == "MOBILE_MONEY":
        if payment.statut == "EN_ATTENTE":
            if payment.provider_status == "queued_offline":
                return "En attente reseau - paiement Mobile Money non encore transmis au provider."
            return "La confirmation Mobile Money est toujours en attente."
        if payment.statut == "ECHOUE":
            error_code = extract_error_code(payment.raw_payload)
            if error_code == "INSUFFICIENT_FUND_ERROR":
                return "Fonds insuffisants sur le wallet du patient."
            return "Le paiement Mobile Money a echoue et peut etre relance."
        if payment.statut == "CONFIRME":
            return "Ce dossier est deja regle."

    if payment.moyen_paiement == "CHEQUE":
        if payment.statut == "RECU":
            return "Cheque en attente de confirmation bancaire."
        if payment.statut == "ENCAISSE":
            return "Cheque confirme par la banque."
        if payment.statut == "REJETE":
            return "Le cheque a ete rejete par la banque. Ce dossier reste bloque pour la caisse."

    if payment.moyen_paiement == "ESPECES" and payment.statut == "CONFIRME":
        return "Ce dossier est deja regle."

    return None


def transaction_can_reopen_in_cashier(transaction: Transaction) -> bool:
    payment = transaction.latest_payment
    if payment is None:
        return False
    return (
        transaction.statut == "ECHOUE"
        and payment.moyen_paiement == "MOBILE_MONEY"
        and payment.statut == "ECHOUE"
    )
