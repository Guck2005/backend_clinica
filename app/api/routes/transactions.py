from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_roles
from app.core.audit import log_audit
from app.core.finance import (
    deliver_invoice_sms,
    transaction_blocking_reason,
    transaction_can_reopen_in_cashier,
    upsert_invoice_for_transaction,
)
from app.db.session import get_db
from app.core.sync_jobs import (
    apply_provider_status,
    is_networkish_provider_error,
    process_pending_sync_jobs,
    queue_mobile_money_refresh,
    queue_mobile_money_initiation,
    resolve_mobile_money_phone_or_error,
)
from app.integrations.fedapay import (
    FedaPayProviderError,
    extract_amount_debited,
    extract_error_code,
    extract_provider_fees,
    extract_provider_mode,
    get_fedapay_provider,
)
from app.models.catalogue import CatalogueItem
from app.models.transaction import Payment, Transaction, TransactionLine
from app.models.user import User
from app.models.visit import Visit
from app.schemas.transaction import (
    MobileMoneyRetryRequest,
    PaymentRead,
    TransactionCreate,
    TransactionListResponse,
    TransactionLineRead,
    TransactionRead,
    TransactionSummaryRead,
)


router = APIRouter(prefix="/transactions", tags=["transactions"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_merchant_reference(visit: Visit, transaction: Transaction, attempt_no: int) -> str:
    nonce = uuid4().hex[:8].upper()
    return f"{visit.id_visite}-TX-{transaction.id}-ATT-{attempt_no}-{nonce}"


def payment_to_read(payment: Payment) -> PaymentRead:
    provider_error_code = extract_error_code(payment.raw_payload)
    provider_mode = extract_provider_mode(payment.raw_payload)
    provider_amount_debited_fcfa = extract_amount_debited(payment.raw_payload)
    provider_fees_fcfa = extract_provider_fees(payment.raw_payload)
    raw_payload = payment.raw_payload or {}
    montant_recu_fcfa = raw_payload.get("montant_recu_fcfa") if isinstance(raw_payload, dict) else None
    monnaie_rendue_fcfa = raw_payload.get("monnaie_rendue_fcfa") if isinstance(raw_payload, dict) else None
    return PaymentRead(
        id=payment.id,
        attempt_no=payment.attempt_no,
        moyen_paiement=payment.moyen_paiement,
        statut=payment.statut,
        montant_fcfa=payment.montant_fcfa,
        provider=payment.provider,
        provider_attempt_id=payment.provider_attempt_id,
        provider_status=payment.provider_status,
        operator_code=payment.operator_code,
        reference_paiement=payment.reference_paiement,
        provider_error_code=provider_error_code,
        provider_mode=provider_mode,
        provider_amount_debited_fcfa=provider_amount_debited_fcfa,
        provider_fees_fcfa=provider_fees_fcfa,
        montant_recu_fcfa=montant_recu_fcfa if isinstance(montant_recu_fcfa, int) else None,
        monnaie_rendue_fcfa=monnaie_rendue_fcfa if isinstance(monnaie_rendue_fcfa, int) else None,
        telephone_paiement=payment.telephone_paiement,
        cheque_numero=payment.cheque_numero,
        cheque_banque=payment.cheque_banque,
        cheque_titulaire=payment.cheque_titulaire,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        confirmed_at=payment.confirmed_at,
        failed_at=payment.failed_at,
    )


def transaction_to_read(transaction: Transaction) -> TransactionRead:
    if transaction.visit.id_visite is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Visit identifier missing")
    payment = transaction.latest_payment
    if payment is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Payment missing")
    return TransactionRead(
        id=transaction.id,
        id_visite=transaction.visit.id_visite,
        patient_nom=f"{transaction.visit.patient_nom} {transaction.visit.patient_prenom}".strip(),
        patient_tel=transaction.visit.patient_tel,
        caisse_id=transaction.caisse_id,
        caissier_id=transaction.caissier_id,
        statut=transaction.statut,
        montant_total_fcfa=transaction.montant_total_fcfa,
        montant_encaisse_fcfa=transaction.montant_encaisse_fcfa,
        invoice_number=transaction.invoice.numero_facture if transaction.invoice else None,
        invoice_status=transaction.invoice.statut_document if transaction.invoice else None,
        can_reopen_in_cashier=transaction_can_reopen_in_cashier(transaction),
        blocking_reason=transaction_blocking_reason(transaction),
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
        lines=[
            TransactionLineRead(
                id=line.id,
                catalogue_item_id=line.catalogue_item_id,
                code_element_snapshot=line.code_element_snapshot,
                nom_snapshot=line.nom_snapshot,
                type_snapshot=line.type_snapshot,
                service_snapshot=line.service_snapshot,
                quantite=line.quantite,
                prix_unitaire_fcfa=line.prix_unitaire_fcfa,
                montant_ligne_fcfa=line.montant_ligne_fcfa,
                payable=line.payable,
                motif_non_honore=line.motif_non_honore,
                created_at=line.created_at,
            )
            for line in transaction.lines
        ],
        payment=payment_to_read(payment),
    )


def get_transaction_query():
    return (
        select(Transaction)
        .options(
            selectinload(Transaction.visit),
            selectinload(Transaction.caisse),
            selectinload(Transaction.caissier),
            selectinload(Transaction.lines),
            selectinload(Transaction.payments),
            selectinload(Transaction.invoice),
        )
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
    )


def get_transaction_by_visit(db: Session, id_visite: str) -> Transaction | None:
    query = get_transaction_query().join(Visit).where(Visit.id_visite == id_visite.upper().strip())
    return db.scalar(query)


def get_transaction_by_id(db: Session, transaction_id: int) -> Transaction | None:
    query = get_transaction_query().where(Transaction.id == transaction_id)
    return db.scalar(query)


def ensure_transaction_access(transaction: Transaction, user: User) -> None:
    if user.role in {"admin", "superviseur", "auditeur"}:
        return
    if user.role == "caissier" and transaction.caisse_id == user.caisse_id:
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")


def calculate_final_status(transaction: Transaction) -> str:
    has_non_payable = any(not line.payable for line in transaction.lines)
    return "PARTIELLEMENT_SOLDE" if has_non_payable else "SOLDE"


def ensure_mobile_money_payment(transaction: Transaction) -> Payment:
    payment = transaction.latest_payment
    if payment is None or payment.moyen_paiement != "MOBILE_MONEY" or payment.provider != "FEDAPAY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette transaction n'utilise pas le flux Mobile Money FedaPay.",
        )
    return payment


def transaction_counts_in_summary(transaction: Transaction) -> bool:
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


def filter_transactions(
    *,
    transactions: list[Transaction],
    user: User,
    search: str | None,
    payment_method: str | None,
    payment_status: str | None,
    date_from: date | None,
    date_to: date | None,
) -> list[Transaction]:
    filtered: list[Transaction] = []
    query = (search or "").strip().lower()

    for transaction in transactions:
        if user.role == "caissier" and transaction.caisse_id != user.caisse_id:
            continue

        payment = transaction.latest_payment
        visit = transaction.visit
        if payment is None or visit.id_visite is None:
            continue

        created_on = transaction.created_at.date()
        if date_from and created_on < date_from:
            continue
        if date_to and created_on > date_to:
            continue
        if payment_method and payment.moyen_paiement != payment_method:
            continue
        if payment_status and payment.statut != payment_status:
            continue

        if query:
            patient_full_name = f"{visit.patient_nom} {visit.patient_prenom}".strip().lower()
            tokens = [
                visit.id_visite.lower(),
                visit.patient_nom.lower(),
                visit.patient_prenom.lower(),
                patient_full_name,
                (visit.patient_tel or "").lower(),
                (visit.patient_tel_normalized or "").lower(),
                (payment.reference_paiement or "").lower(),
                (payment.cheque_numero or "").lower(),
            ]
            if not any(query in token for token in tokens):
                continue

        filtered.append(transaction)

    return filtered


def build_transaction_summary(transactions: list[Transaction]) -> TransactionSummaryRead:
    encaisse_fcfa = 0
    especes_fcfa = 0
    cheques_fcfa = 0
    momo_fcfa = 0

    for transaction in transactions:
        payment = transaction.latest_payment
        if payment is None or not transaction_counts_in_summary(transaction):
            continue

        encaisse_fcfa += transaction.montant_encaisse_fcfa
        if payment.moyen_paiement == "ESPECES":
            especes_fcfa += transaction.montant_encaisse_fcfa
        elif payment.moyen_paiement == "CHEQUE":
            cheques_fcfa += transaction.montant_encaisse_fcfa
        elif payment.moyen_paiement == "MOBILE_MONEY":
            momo_fcfa += transaction.montant_encaisse_fcfa

    return TransactionSummaryRead(
        encaisse_fcfa=encaisse_fcfa,
        especes_fcfa=especes_fcfa,
        cheques_fcfa=cheques_fcfa,
        momo_fcfa=momo_fcfa,
    )


def start_fedapay_attempt(
    *,
    db: Session,
    user: User,
    transaction: Transaction,
    visit: Visit,
    amount_fcfa: int,
    attempt_no: int,
    phone_number: str,
) -> Payment:
    normalized_phone, formatted_phone, operator_code = resolve_mobile_money_phone_or_error(phone_number)

    provider = get_fedapay_provider()
    last_error: FedaPayProviderError | None = None
    for _ in range(3):
        merchant_reference = build_merchant_reference(visit, transaction, attempt_no)
        try:
            initiation = provider.start_mobile_money_payment(
                amount_fcfa=amount_fcfa,
                description=f"Encaissement {visit.id_visite}",
                merchant_reference=merchant_reference,
                operator_code=operator_code,
                phone_number=normalized_phone,
                metadata={
                    "visit_id": visit.id_visite,
                    "transaction_id": transaction.id,
                    "attempt_no": attempt_no,
                    "caissier_id": transaction.caissier_id,
                    "merchant_reference": merchant_reference,
                },
            )
            break
        except FedaPayProviderError as exc:
            last_error = exc
            if is_networkish_provider_error(exc):
                queued_payment = Payment(
                    attempt_no=attempt_no,
                    moyen_paiement="MOBILE_MONEY",
                    statut="EN_ATTENTE",
                    montant_fcfa=amount_fcfa,
                    provider="FEDAPAY",
                    provider_attempt_id=None,
                    provider_status="queued_offline",
                    operator_code=operator_code,
                    reference_paiement=None,
                    telephone_paiement=formatted_phone,
                    cheque_numero=None,
                    cheque_banque=None,
                    cheque_titulaire=None,
                    raw_payload={"queued_offline": True},
                )
                return queue_mobile_money_initiation(
                    db,
                    transaction=transaction,
                    payment=queued_payment,
                    visit=visit,
                    actor=user,
                    normalized_phone=normalized_phone,
                    formatted_phone=formatted_phone,
                    operator_code=operator_code,
                )
            if "merchant_reference" not in exc.message:
                raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    else:
        if last_error is None:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Echec de creation de la transaction FedaPay.")
        raise HTTPException(status_code=last_error.status_code, detail=last_error.message) from last_error

    return Payment(
        attempt_no=attempt_no,
        moyen_paiement="MOBILE_MONEY",
        statut="EN_ATTENTE",
        montant_fcfa=amount_fcfa,
        provider="FEDAPAY",
        provider_attempt_id=initiation.provider_attempt_id,
        provider_status=initiation.provider_status,
        operator_code=initiation.operator_code,
        reference_paiement=None,
        telephone_paiement=formatted_phone,
        cheque_numero=None,
        cheque_banque=None,
        cheque_titulaire=None,
        raw_payload=initiation.raw_payload,
    )


def build_transaction_lines(
    *,
    db: Session,
    payload_lines: list,
) -> tuple[list[TransactionLine], int, int]:
    if not payload_lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Au moins une ligne est obligatoire.",
        )

    catalogue_item_ids = [line.catalogue_item_id for line in payload_lines]
    if len(set(catalogue_item_ids)) != len(catalogue_item_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un element catalogue ne peut apparaitre qu'une seule fois.",
        )

    catalogue_items = db.scalars(select(CatalogueItem).where(CatalogueItem.id.in_(catalogue_item_ids))).all()
    catalogue_by_id = {item.id: item for item in catalogue_items}

    line_models: list[TransactionLine] = []
    montant_total_fcfa = 0
    montant_encaisse_fcfa = 0

    for line_payload in payload_lines:
        item = catalogue_by_id.get(line_payload.catalogue_item_id)
        if item is None or not item.actif:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Element catalogue invalide: {line_payload.catalogue_item_id}.",
            )

        motif = (line_payload.motif_non_honore or "").strip()
        if not line_payload.payable and not motif:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Toute ligne non honoree doit avoir un motif.",
            )

        montant_ligne_fcfa = item.montant_fcfa * line_payload.quantite
        montant_total_fcfa += montant_ligne_fcfa
        if line_payload.payable:
            montant_encaisse_fcfa += montant_ligne_fcfa

        line_models.append(
            TransactionLine(
                catalogue_item_id=item.id,
                code_element_snapshot=item.code_element,
                nom_snapshot=item.nom,
                type_snapshot=item.type,
                service_snapshot=item.service,
                quantite=line_payload.quantite,
                prix_unitaire_fcfa=item.montant_fcfa,
                montant_ligne_fcfa=montant_ligne_fcfa,
                payable=line_payload.payable,
                motif_non_honore=motif or None,
            )
        )

    if montant_encaisse_fcfa <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Il doit exister au moins une ligne payable.",
        )

    return line_models, montant_total_fcfa, montant_encaisse_fcfa


def next_payment_attempt_no(transaction: Transaction) -> int:
    payment = transaction.latest_payment
    if payment is None:
        return 1
    return payment.attempt_no + 1


def apply_transaction_draft(
    *,
    transaction: Transaction,
    visit: Visit,
    user: User,
    line_models: list[TransactionLine],
    montant_total_fcfa: int,
    montant_encaisse_fcfa: int,
) -> None:
    transaction.visit_id = visit.id
    transaction.visit = visit
    transaction.caisse_id = user.caisse_id if user.role == "caissier" else None
    transaction.caissier_id = user.id
    transaction.lines = line_models
    transaction.montant_total_fcfa = montant_total_fcfa
    transaction.montant_encaisse_fcfa = montant_encaisse_fcfa


def append_payment_attempt(
    *,
    db: Session,
    transaction: Transaction,
    visit: Visit,
    user: User,
    payment_payload,
) -> None:
    attempt_no = next_payment_attempt_no(transaction)
    montant_encaisse_fcfa = transaction.montant_encaisse_fcfa

    if payment_payload.moyen_paiement == "ESPECES":
        if payment_payload.montant_recu_fcfa is None or payment_payload.montant_recu_fcfa < montant_encaisse_fcfa:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Le montant recu en especes doit couvrir le montant a encaisser.",
            )

        transaction.payments.append(
            Payment(
                attempt_no=attempt_no,
                moyen_paiement="ESPECES",
                montant_fcfa=montant_encaisse_fcfa,
                reference_paiement=None,
                telephone_paiement=None,
                cheque_numero=None,
                cheque_banque=None,
                cheque_titulaire=None,
                statut="CONFIRME",
                raw_payload={
                    "montant_recu_fcfa": payment_payload.montant_recu_fcfa,
                    "monnaie_rendue_fcfa": payment_payload.montant_recu_fcfa - montant_encaisse_fcfa,
                },
            )
        )
        transaction.statut = calculate_final_status(transaction)
        visit.statut = transaction.statut
        return

    if payment_payload.moyen_paiement == "MOBILE_MONEY":
        if (payment_payload.reference_paiement or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La reference Mobile Money vient uniquement de FedaPay.",
            )

        transaction.statut = "EN_ATTENTE"
        visit.statut = "EN_CAISSE"
        db.flush()
        transaction.payments.append(
            start_fedapay_attempt(
                db=db,
                user=user,
                transaction=transaction,
                visit=visit,
                amount_fcfa=montant_encaisse_fcfa,
                attempt_no=attempt_no,
                phone_number=payment_payload.telephone_paiement or visit.patient_tel,
            )
        )
        return

    cheque_numero = (payment_payload.cheque_numero or "").strip()
    cheque_banque = (payment_payload.cheque_banque or "").strip()
    cheque_titulaire = (payment_payload.cheque_titulaire or "").strip()
    if not cheque_numero or not cheque_banque or not cheque_titulaire:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les informations du cheque sont obligatoires.",
        )

    transaction.payments.append(
        Payment(
            attempt_no=attempt_no,
            moyen_paiement="CHEQUE",
            montant_fcfa=montant_encaisse_fcfa,
            reference_paiement=None,
            telephone_paiement=None,
            cheque_numero=cheque_numero,
            cheque_banque=cheque_banque,
            cheque_titulaire=cheque_titulaire,
            statut="RECU",
        )
    )
    transaction.statut = calculate_final_status(transaction)
    visit.statut = transaction.statut


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    search: str | None = None,
    payment_method: str | None = None,
    payment_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> TransactionListResponse:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 200)
    items = db.scalars(get_transaction_query()).all()
    filtered = filter_transactions(
        transactions=items,
        user=user,
        search=search,
        payment_method=payment_method,
        payment_status=payment_status,
        date_from=date_from,
        date_to=date_to,
    )
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return TransactionListResponse(
        items=[transaction_to_read(item) for item in filtered[start:end]],
        total=len(filtered),
        summary=build_transaction_summary(filtered),
    )


@router.get("/by-visit/{id_visite}", response_model=TransactionRead)
def get_transaction_for_visit(
    id_visite: str,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> TransactionRead:
    transaction = get_transaction_by_visit(db, id_visite)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    ensure_transaction_access(transaction, user)
    return transaction_to_read(transaction)


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    user: User = Depends(require_roles("caissier", "admin")),
    db: Session = Depends(get_db),
) -> TransactionRead:
    id_visite = payload.id_visite.upper().strip()
    visit = db.scalar(select(Visit).where(Visit.id_visite == id_visite))
    if visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")

    if user.role == "caissier" and user.caisse_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce caissier n'a pas de caisse active affectee.",
        )

    existing_transaction = get_transaction_by_visit(db, id_visite)
    if visit.statut in {"SOLDE", "PARTIELLEMENT_SOLDE"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce dossier a deja un encaissement en cours ou finalise.",
        )

    transaction: Transaction
    if existing_transaction is None:
        transaction = Transaction(visit_id=visit.id)
        db.add(transaction)
    else:
        ensure_transaction_access(existing_transaction, user)
        if not transaction_can_reopen_in_cashier(existing_transaction):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=transaction_blocking_reason(existing_transaction) or "Ce dossier a deja un encaissement en cours ou finalise.",
            )

        transaction = existing_transaction

    line_models, montant_total_fcfa, montant_encaisse_fcfa = build_transaction_lines(
        db=db,
        payload_lines=payload.lignes,
    )
    apply_transaction_draft(
        transaction=transaction,
        visit=visit,
        user=user,
        line_models=line_models,
        montant_total_fcfa=montant_total_fcfa,
        montant_encaisse_fcfa=montant_encaisse_fcfa,
    )
    append_payment_attempt(
        db=db,
        transaction=transaction,
        visit=visit,
        user=user,
        payment_payload=payload.paiement,
    )
    had_invoice = transaction.invoice is not None
    invoice = upsert_invoice_for_transaction(db, transaction)
    if invoice is not None:
        deliver_invoice_sms(db, invoice)
    db.flush()
    log_audit(
        db,
        action_code="TRANSACTION_CREATED",
        action_label="Creation de transaction d'encaissement",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        actor=user,
        caisse_id=transaction.caisse_id,
        detail={
            "visit_id": visit.id_visite,
            "payment_method": transaction.latest_payment.moyen_paiement if transaction.latest_payment else None,
            "transaction_status": transaction.statut,
        },
    )
    if invoice is not None and not had_invoice:
        log_audit(
            db,
            action_code="INVOICE_CREATED",
            action_label="Creation de facture",
            entity_type="INVOICE",
            entity_id=invoice.numero_facture,
            actor=user,
            caisse_id=transaction.caisse_id,
            detail={"visit_id": visit.id_visite},
        )

    db.commit()

    created = get_transaction_by_visit(db, id_visite)
    if created is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transaction creation failed")
    return transaction_to_read(created)


@router.post("/{transaction_id}/payments/mobile-money/retry", response_model=TransactionRead)
def retry_mobile_money_payment(
    transaction_id: int,
    payload: MobileMoneyRetryRequest | None = None,
    user: User = Depends(require_roles("caissier", "admin")),
    db: Session = Depends(get_db),
) -> TransactionRead:
    transaction = get_transaction_by_id(db, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    ensure_transaction_access(transaction, user)
    payment = ensure_mobile_money_payment(transaction)

    if transaction.statut in {"SOLDE", "PARTIELLEMENT_SOLDE"} or payment.statut == "CONFIRME":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette transaction est deja finalisee.")
    if payment.statut != "ECHOUE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La relance Mobile Money est autorisee seulement apres un echec.",
        )

    next_attempt = payment.attempt_no + 1
    transaction.statut = "EN_ATTENTE"
    transaction.visit.statut = "EN_CAISSE"
    transaction.payments.append(
        start_fedapay_attempt(
            db=db,
            user=user,
            transaction=transaction,
            visit=transaction.visit,
            amount_fcfa=transaction.montant_encaisse_fcfa,
            attempt_no=next_attempt,
            phone_number=(payload.telephone_paiement if payload else None) or payment.telephone_paiement or transaction.visit.patient_tel,
        )
    )
    invoice = upsert_invoice_for_transaction(db, transaction)
    if invoice is not None:
        deliver_invoice_sms(db, invoice)
    log_audit(
        db,
        action_code="PAYMENT_RETRIED",
        action_label="Relance de paiement Mobile Money",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        actor=user,
        caisse_id=transaction.caisse_id,
        detail={"attempt_no": next_attempt},
    )
    db.commit()

    refreshed = get_transaction_by_id(db, transaction_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transaction refresh failed")
    return transaction_to_read(refreshed)


@router.post("/{transaction_id}/refresh-provider-status", response_model=TransactionRead)
def refresh_provider_status(
    transaction_id: int,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> TransactionRead:
    transaction = get_transaction_by_id(db, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    ensure_transaction_access(transaction, user)
    payment = ensure_mobile_money_payment(transaction)
    if payment.provider_status == "queued_offline":
        process_pending_sync_jobs(db)
        db.commit()
        transaction = get_transaction_by_id(db, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        payment = ensure_mobile_money_payment(transaction)
    if not payment.provider_attempt_id:
        return transaction_to_read(transaction)

    provider = get_fedapay_provider()
    try:
        provider_status = provider.fetch_transaction_status(payment.provider_attempt_id)
    except FedaPayProviderError as exc:
        if is_networkish_provider_error(exc):
            queue_mobile_money_refresh(db, transaction=transaction, payment=payment, actor=user)
            db.commit()
            refreshed = get_transaction_by_id(db, transaction_id)
            if refreshed is None:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transaction refresh failed")
            return transaction_to_read(refreshed)
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
        action_code="PAYMENT_REFRESHED",
        action_label="Verification de statut Mobile Money",
        entity_type="TRANSACTION",
        entity_id=str(transaction.id),
        actor=user,
        caisse_id=transaction.caisse_id,
        detail={"payment_status": payment.statut, "provider_status": payment.provider_status},
    )
    db.commit()

    refreshed = get_transaction_by_id(db, transaction_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transaction refresh failed")
    return transaction_to_read(refreshed)
