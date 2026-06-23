from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, get_db, require_roles
from app.api.routes.transactions import get_transaction_query
from app.core.alerting import upsert_named_alert
from app.core.audit import log_audit
from app.core.finance import deliver_invoice_sms, patient_full_name, upsert_invoice_for_transaction, utcnow
from app.core.sync_jobs import apply_provider_status
from app.integrations.fedapay import FedaPayProviderError, get_fedapay_provider
from app.models.invoice import Invoice
from app.models.transaction import Payment, Transaction
from app.models.user import User
from app.schemas.payment import (
    ChequePaymentListResponse,
    ChequePaymentRead,
    ChequePaymentStatusUpdate,
)


router = APIRouter(prefix="/payments", tags=["payments"])


def cheque_payment_to_read(payment: Payment, invoice_number: str | None) -> ChequePaymentRead:
    transaction = payment.transaction
    visit = transaction.visit
    if visit.id_visite is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Visit identifier missing")
    return ChequePaymentRead(
        payment_id=payment.id,
        transaction_id=transaction.id,
        id_visite=visit.id_visite,
        caisse_id=transaction.caisse_id,
        caisse_nom=transaction.caisse.nom if transaction.caisse else None,
        patient_nom=patient_full_name(transaction),
        patient_tel=visit.patient_tel,
        montant_fcfa=payment.montant_fcfa,
        statut=payment.statut,  # type: ignore[arg-type]
        cheque_numero=payment.cheque_numero or "",
        cheque_banque=payment.cheque_banque or "",
        cheque_titulaire=payment.cheque_titulaire or "",
        invoice_number=invoice_number,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def append_payment_history(payment: Payment, *, actor: User, action: str) -> None:
    raw_payload = payment.raw_payload if isinstance(payment.raw_payload, dict) else {}
    history = raw_payload.get("status_history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "action": action,
            "acteur_id": actor.id,
            "acteur_role": actor.role,
            "timestamp": utcnow().isoformat(),
        }
    )
    raw_payload["status_history"] = history
    payment.raw_payload = raw_payload


@router.get("/cheques", response_model=ChequePaymentListResponse)
def list_cheque_payments(
    status: str | None = None,
    search: str | None = None,
    caisse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    _: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> ChequePaymentListResponse:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 200)
    payments = db.scalars(
        select(Payment)
        .where(Payment.moyen_paiement == "CHEQUE")
        .options(
            selectinload(Payment.transaction).selectinload(Transaction.visit),
            selectinload(Payment.transaction).selectinload(Transaction.caisse),
        )
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    ).all()

    query = (search or "").strip().lower()
    filtered: list[Payment] = []
    for payment in payments:
        transaction = payment.transaction
        visit = transaction.visit
        if visit.id_visite is None:
            continue
        created_on = payment.created_at.date()
        if status and payment.statut != status:
            continue
        if caisse_id is not None and transaction.caisse_id != caisse_id:
            continue
        if date_from and created_on < date_from:
            continue
        if date_to and created_on > date_to:
            continue
        if query:
            tokens = [
                visit.id_visite.lower(),
                visit.patient_nom.lower(),
                visit.patient_prenom.lower(),
                patient_full_name(transaction).lower(),
                (visit.patient_tel or "").lower(),
                (payment.cheque_numero or "").lower(),
                (payment.cheque_banque or "").lower(),
            ]
            if not any(query in token for token in tokens):
                continue
        filtered.append(payment)

    page_items = filtered[(safe_page - 1) * safe_page_size : safe_page * safe_page_size]
    invoice_by_transaction = {
        invoice.transaction_id: invoice.numero_facture
        for invoice in db.scalars(
            select(Invoice).where(Invoice.transaction_id.in_([payment.transaction_id for payment in page_items]))
        ).all()
    } if page_items else {}

    return ChequePaymentListResponse(
        items=[cheque_payment_to_read(payment, invoice_by_transaction.get(payment.transaction_id)) for payment in page_items],
        total=len(filtered),
    )


@router.patch("/cheques/{payment_id}/status", response_model=ChequePaymentRead)
def update_cheque_payment_status(
    payment_id: int,
    payload: ChequePaymentStatusUpdate,
    user: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> ChequePaymentRead:
    payment = db.scalar(
        select(Payment)
        .where(Payment.id == payment_id)
        .options(
            selectinload(Payment.transaction).selectinload(Transaction.visit),
            selectinload(Payment.transaction).selectinload(Transaction.caisse),
        )
    )
    if payment is None or payment.moyen_paiement != "CHEQUE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paiement cheque introuvable.")

    transaction = payment.transaction
    if payment.statut == payload.statut:
        invoice = upsert_invoice_for_transaction(db, transaction)
        db.commit()
        return cheque_payment_to_read(payment, invoice.numero_facture if invoice else None)

    if payment.statut != "RECU":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce cheque a deja ete traite et ne peut plus changer de statut.",
        )

    payment.statut = payload.statut
    payment.updated_at = utcnow()
    append_payment_history(payment, actor=user, action=payload.statut)
    if payload.statut == "ENCAISSE":
        payment.confirmed_at = payment.confirmed_at or utcnow()
    elif payload.statut == "REJETE":
        payment.failed_at = payment.failed_at or utcnow()
        transaction.statut = "ECHOUE"
        transaction.visit.statut = "EN_CAISSE"

    invoice = upsert_invoice_for_transaction(db, transaction)
    if payload.statut == "REJETE" and invoice is not None:
        upsert_named_alert(
            db,
            rule_code="CHEQUE_REJETE_APRES_FACTURE",
            gravite="haute",
            message=f"Cheque {payment.cheque_numero or ''} rejete apres emission de la facture {invoice.numero_facture}.",
            caisse_id=transaction.caisse_id,
            source_type="CHEQUE_PAYMENT",
            source_id=str(payment.id),
            impact_amount_fcfa=payment.montant_fcfa,
            details={
                "pieces_concernees": f"Cheque {payment.cheque_numero or ''} / facture {invoice.numero_facture}",
                "recommandation": "Bloquer le dossier, verifier le rejet bancaire et declencher le traitement administratif du cheque impaye.",
            },
            actor=user,
        )
    log_audit(
        db,
        action_code="PAYMENT_CHEQUE_STATUS_UPDATED",
        action_label="Mise a jour du statut cheque",
        entity_type="PAYMENT",
        entity_id=str(payment.id),
        actor=user,
        caisse_id=transaction.caisse_id,
        detail={"statut": payload.statut, "invoice_number": invoice.numero_facture if invoice else None},
    )

    db.commit()
    return cheque_payment_to_read(payment, invoice.numero_facture if invoice else None)


@router.post("/fedapay/webhook", status_code=status.HTTP_202_ACCEPTED)
async def fedapay_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    raw_body = await request.body()
    signature = request.headers.get("X-FEDAPAY-SIGNATURE")
    provider = get_fedapay_provider()
    if not provider.verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid FedaPay signature")

    try:
        payload = await request.json()
    except Exception as exc:  # pragma: no cover - FastAPI/Starlette error path
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook payload")

    provider_attempt_id = provider.extract_webhook_transaction_id(payload)
    if not provider_attempt_id:
        return {"status": "ignored"}

    payment = db.scalar(select(Payment).where(Payment.provider_attempt_id == provider_attempt_id))
    if payment is None:
        return {"status": "ignored"}

    transaction = db.scalar(get_transaction_query().where(Transaction.id == payment.transaction_id))
    if transaction is None:
        return {"status": "ignored"}

    latest_payment = transaction.latest_payment
    if latest_payment is None or latest_payment.id != payment.id:
        return {"status": "ignored"}

    try:
        provider_status = provider.fetch_transaction_status(provider_attempt_id)
    except FedaPayProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    apply_provider_status(
        transaction,
        payment,
        provider_status.provider_status,
        provider_status.reference_paiement,
        provider_status.raw_payload,
    )
    invoice = upsert_invoice_for_transaction(db, transaction)
    if invoice is not None:
        deliver_invoice_sms(db, invoice)
    log_audit(
        db,
        action_code="PAYMENT_PROVIDER_WEBHOOK",
        action_label="Webhook provider Mobile Money traite",
        entity_type="PAYMENT",
        entity_id=str(payment.id),
        actor=None,
        caisse_id=transaction.caisse_id,
        detail={"provider_status": payment.provider_status, "payment_status": payment.statut},
    )
    db.commit()
    return {"status": "accepted"}
