from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, require_roles
from app.core.audit import log_audit
from app.core.finance import (
    build_invoice_download_url,
    build_invoice_public_download_url,
    deliver_invoice_sms,
)
from app.core.invoice_pdf_service import render_invoice_pdf
from app.models.invoice import Invoice
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.invoice import InvoiceListResponse, InvoiceRead


router = APIRouter(tags=["factures"])


def get_invoice_query():
    return select(Invoice).options(
        selectinload(Invoice.transaction).selectinload(Transaction.visit),
        selectinload(Invoice.transaction).selectinload(Transaction.caisse),
        selectinload(Invoice.transaction).selectinload(Transaction.caissier),
        selectinload(Invoice.transaction).selectinload(Transaction.lines),
        selectinload(Invoice.transaction).selectinload(Transaction.payments),
    )


def invoice_to_read(invoice: Invoice) -> InvoiceRead:
    return InvoiceRead(
        numero_facture=invoice.numero_facture,
        visit_id=invoice.id_visite_snapshot,
        patient_nom=invoice.patient_nom_snapshot,
        patient_tel=invoice.patient_tel_snapshot,
        moyen_paiement=invoice.moyen_paiement_snapshot,
        reference=invoice.reference_snapshot,
        statut_document=invoice.statut_document,  # type: ignore[arg-type]
        mention_paiement=invoice.mention_paiement,
        download_url=build_invoice_download_url(invoice),
        public_download_url=build_invoice_public_download_url(invoice),
        sms_status=invoice.sms_status,  # type: ignore[arg-type]
        sms_sent_at=invoice.sms_sent_at,
        sms_error=invoice.sms_error,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def can_read_invoice(invoice: Invoice, user: User) -> bool:
    if user.role in {"admin", "superviseur", "auditeur"}:
        return True
    return user.role == "caissier" and invoice.transaction.caisse_id == user.caisse_id


def get_invoice_by_number(db: Session, numero_facture: str) -> Invoice | None:
    return db.scalar(
        get_invoice_query().where(Invoice.numero_facture == numero_facture.upper().strip())
    )


@router.get("/factures", response_model=InvoiceListResponse)
def list_factures(
    search: str | None = None,
    payment_method: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> InvoiceListResponse:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 200)
    invoices = db.scalars(
        get_invoice_query().order_by(Invoice.created_at.desc(), Invoice.id.desc())
    ).all()

    query = (search or "").strip().lower()
    filtered = []
    for invoice in invoices:
        if not can_read_invoice(invoice, user):
            continue
        if payment_method and invoice.moyen_paiement_snapshot != payment_method:
            continue
        if status_filter and invoice.statut_document != status_filter:
            continue
        if query:
            tokens = [
                invoice.numero_facture.lower(),
                invoice.id_visite_snapshot.lower(),
                invoice.patient_nom_snapshot.lower(),
                (invoice.patient_tel_snapshot or "").lower(),
                (invoice.reference_snapshot or "").lower(),
            ]
            if not any(query in token for token in tokens):
                continue
        filtered.append(invoice)

    page_items = filtered[(safe_page - 1) * safe_page_size : safe_page * safe_page_size]
    return InvoiceListResponse(items=[invoice_to_read(item) for item in page_items], total=len(filtered))


@router.get("/factures/{numero_facture}/pdf")
def get_facture_pdf(
    numero_facture: str,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> Response:
    invoice = get_invoice_by_number(db, numero_facture)
    if invoice is None or not can_read_invoice(invoice, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facture introuvable.")

    pdf_bytes = render_invoice_pdf(invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{invoice.numero_facture}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/factures/{numero_facture}/send-sms", response_model=InvoiceRead)
def send_facture_sms(
    numero_facture: str,
    user: User = Depends(require_roles("caissier", "admin", "superviseur")),
    db: Session = Depends(get_db),
) -> InvoiceRead:
    invoice = get_invoice_by_number(db, numero_facture)
    if invoice is None or not can_read_invoice(invoice, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facture introuvable.")

    deliver_invoice_sms(db, invoice, force=True)
    log_audit(
        db,
        action_code="INVOICE_SMS_SENT",
        action_label="Envoi ou renvoi de facture par SMS",
        entity_type="INVOICE",
        entity_id=invoice.numero_facture,
        actor=user,
        caisse_id=invoice.transaction.caisse_id,
        detail={"sms_status": invoice.sms_status},
    )
    db.commit()
    db.refresh(invoice)
    return invoice_to_read(invoice)


@router.get("/factures/{numero_facture}", response_model=InvoiceRead)
def get_facture(
    numero_facture: str,
    user: User = Depends(require_roles("caissier", "admin", "superviseur", "auditeur")),
    db: Session = Depends(get_db),
) -> InvoiceRead:
    invoice = get_invoice_by_number(db, numero_facture)
    if invoice is None or not can_read_invoice(invoice, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facture introuvable.")
    return invoice_to_read(invoice)


@router.get("/public/factures/{public_token}.pdf")
def get_public_facture_pdf(public_token: str, db: Session = Depends(get_db)) -> Response:
    invoice = db.scalar(get_invoice_query().where(Invoice.public_token == public_token.strip()))
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facture introuvable.")

    pdf_bytes = render_invoice_pdf(invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{invoice.numero_facture}.pdf"',
            "Cache-Control": "no-store",
        },
    )
