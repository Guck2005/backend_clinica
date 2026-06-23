from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.audit import log_audit
from app.core.finance import deliver_invoice_sms, upsert_invoice_for_transaction
from app.core.phone import deduce_benin_mobile_operator, format_phone, normalize_phone
from app.integrations.fedapay import FedaPayProviderError, get_fedapay_provider
from app.models.sync_job import SyncJob
from app.models.transaction import Payment, Transaction
from app.models.user import User
from app.models.visit import Visit


NETWORK_ERROR_HINTS = (
    "Impossible de contacter FedaPay",
    "temporarily unavailable",
    "timeout",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_networkish_provider_error(exc: FedaPayProviderError) -> bool:
    if exc.status_code >= 500:
        return True
    lowered = exc.message.lower()
    return any(hint.lower() in lowered for hint in NETWORK_ERROR_HINTS)


def create_sync_job(
    db: Session,
    *,
    job_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> SyncJob:
    job = SyncJob(
        job_type=job_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=payload or None,
        status="PENDING",
        scheduled_at=utcnow(),
    )
    db.add(job)
    db.flush()
    return job


def queue_mobile_money_initiation(
    db: Session,
    *,
    transaction: Transaction,
    payment: Payment,
    visit: Visit,
    actor: User | None,
    normalized_phone: str,
    formatted_phone: str,
    operator_code: str,
) -> Payment:
    payment.provider = "FEDAPAY"
    payment.provider_status = "queued_offline"
    payment.operator_code = operator_code
    payment.telephone_paiement = formatted_phone
    payment.raw_payload = {
        "queued_offline": True,
        "queued_at": utcnow().isoformat(),
    }
    create_sync_job(
        db,
        job_type="FEDAPAY_INITIATE_MOMO",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        payload={
            "transaction_id": transaction.id,
            "visit_id": visit.id_visite,
            "attempt_no": payment.attempt_no,
            "amount_fcfa": payment.montant_fcfa,
            "phone_number": normalized_phone,
            "operator_code": operator_code,
        },
    )
    log_audit(
        db,
        action_code="SYNC_JOB_CREATED",
        action_label="Paiement Mobile Money mis en file d'attente reseau",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        actor=actor,
        caisse_id=transaction.caisse_id,
        detail={"attempt_no": payment.attempt_no, "phone_number": formatted_phone},
    )
    return payment


def queue_mobile_money_refresh(
    db: Session,
    *,
    transaction: Transaction,
    payment: Payment,
    actor: User | None,
) -> SyncJob:
    payment.provider_status = "queued_offline"
    job = create_sync_job(
        db,
        job_type="FEDAPAY_REFRESH_STATUS",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        payload={
            "transaction_id": transaction.id,
            "payment_id": payment.id,
            "provider_attempt_id": payment.provider_attempt_id,
        },
    )
    log_audit(
        db,
        action_code="SYNC_JOB_CREATED",
        action_label="Verification provider mise en file d'attente reseau",
        entity_type="SYNC_JOB",
        entity_id=str(job.id),
        actor=actor,
        caisse_id=transaction.caisse_id,
        detail={"provider_attempt_id": payment.provider_attempt_id},
    )
    return job


def resolve_mobile_money_phone_or_error(phone_number: str | None) -> tuple[str, str, str]:
    candidate = (phone_number or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le numero Mobile Money est obligatoire.",
        )
    normalized_phone = normalize_phone(candidate)
    operator_code = deduce_benin_mobile_operator(normalized_phone)
    if operator_code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le numero de paiement ne correspond a aucun operateur Mobile Money connu.",
        )
    return normalized_phone, format_phone(normalized_phone), operator_code


def apply_provider_status(transaction: Transaction, payment: Payment, provider_status: str, reference_paiement: str | None, raw_payload: dict[str, Any]) -> None:
    normalized = provider_status.strip().lower()
    payment.provider_status = normalized
    payment.raw_payload = raw_payload
    payment.updated_at = utcnow()

    if normalized == "approved":
        payment.reference_paiement = reference_paiement
        payment.statut = "CONFIRME"
        payment.confirmed_at = payment.confirmed_at or utcnow()
        has_non_payable = any(not line.payable for line in transaction.lines)
        transaction.statut = "PARTIELLEMENT_SOLDE" if has_non_payable else "SOLDE"
        transaction.visit.statut = transaction.statut
        return

    if normalized in {"declined", "canceled", "expired"}:
        payment.reference_paiement = None
        payment.statut = "ECHOUE"
        payment.failed_at = payment.failed_at or utcnow()
        transaction.statut = "ECHOUE"
        if transaction.visit.statut not in {"SOLDE", "PARTIELLEMENT_SOLDE"}:
            transaction.visit.statut = "EN_CAISSE"
        return

    payment.statut = "EN_ATTENTE"
    payment.reference_paiement = None
    transaction.statut = "EN_ATTENTE"
    if transaction.visit.statut not in {"SOLDE", "PARTIELLEMENT_SOLDE"}:
        transaction.visit.statut = "EN_CAISSE"


def process_pending_sync_jobs(db: Session) -> int:
    provider = get_fedapay_provider()
    jobs = db.scalars(
        select(SyncJob)
        .where(SyncJob.status.in_(("PENDING", "FAILED")), SyncJob.scheduled_at <= utcnow())
        .order_by(SyncJob.created_at.asc(), SyncJob.id.asc())
        .limit(20)
    ).all()
    processed = 0

    for job in jobs:
        job.status = "PROCESSING"
        job.retry_count += 1
        db.flush()
        try:
            if job.job_type == "FEDAPAY_INITIATE_MOMO":
                payload = job.payload_json or {}
                transaction = db.scalar(
                    select(Transaction)
                    .where(Transaction.id == int(payload["transaction_id"]))
                    .options(
                        selectinload(Transaction.visit),
                        selectinload(Transaction.lines),
                        selectinload(Transaction.payments),
                        selectinload(Transaction.invoice),
                    )
                )
                if transaction is None or transaction.visit.id_visite is None:
                    raise ValueError("Transaction introuvable pour la sync.")
                payment = transaction.latest_payment
                if payment is None:
                    raise ValueError("Paiement introuvable pour la sync.")
                initiation = provider.start_mobile_money_payment(
                    amount_fcfa=int(payload["amount_fcfa"]),
                    description=f"Encaissement {transaction.visit.id_visite}",
                    merchant_reference=f"{transaction.visit.id_visite}-TX-{transaction.id}-ATT-{payment.attempt_no}-{job.id}",
                    operator_code=str(payload["operator_code"]),
                    phone_number=str(payload["phone_number"]),
                    metadata={
                        "visit_id": transaction.visit.id_visite,
                        "transaction_id": transaction.id,
                        "attempt_no": payment.attempt_no,
                    },
                )
                payment.provider = "FEDAPAY"
                payment.provider_attempt_id = initiation.provider_attempt_id
                payment.provider_status = initiation.provider_status
                payment.operator_code = initiation.operator_code
                payment.telephone_paiement = format_phone(str(payload["phone_number"]))
                payment.raw_payload = initiation.raw_payload
                payment.updated_at = utcnow()
                job.status = "SUCCEEDED"
                job.processed_at = utcnow()
                invoice = upsert_invoice_for_transaction(db, transaction)
                if invoice is not None:
                    deliver_invoice_sms(db, invoice)
            elif job.job_type == "FEDAPAY_REFRESH_STATUS":
                payload = job.payload_json or {}
                transaction = db.scalar(
                    select(Transaction)
                    .where(Transaction.id == int(payload["transaction_id"]))
                    .options(
                        selectinload(Transaction.visit),
                        selectinload(Transaction.lines),
                        selectinload(Transaction.payments),
                        selectinload(Transaction.invoice),
                    )
                )
                if transaction is None:
                    raise ValueError("Transaction introuvable pour la sync.")
                payment = transaction.latest_payment
                if payment is None or not payment.provider_attempt_id:
                    raise ValueError("Tentative provider introuvable pour la sync.")
                status_result = provider.fetch_transaction_status(payment.provider_attempt_id)
                apply_provider_status(
                    transaction,
                    payment,
                    status_result.provider_status,
                    status_result.reference_paiement,
                    status_result.raw_payload,
                )
                job.status = "SUCCEEDED"
                job.processed_at = utcnow()
                invoice = upsert_invoice_for_transaction(db, transaction)
                if invoice is not None:
                    deliver_invoice_sms(db, invoice)
            else:
                job.status = "FAILED"
                job.last_error = "Type de job non pris en charge."
                job.processed_at = utcnow()
            processed += 1
        except FedaPayProviderError as exc:
            if is_networkish_provider_error(exc):
                job.status = "FAILED"
                job.last_error = exc.message[:255]
                job.scheduled_at = utcnow() + timedelta(seconds=min(300, 20 * job.retry_count))
            else:
                job.status = "FAILED"
                job.last_error = exc.message[:255]
                job.processed_at = utcnow()
        except Exception as exc:  # pragma: no cover - defensive worker path
            job.status = "FAILED"
            job.last_error = str(exc)[:255]
            job.processed_at = utcnow()

    return processed
