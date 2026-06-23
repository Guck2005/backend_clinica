from datetime import datetime
from typing import Literal

from pydantic import BaseModel


InvoiceStatus = Literal["EMISE", "EN_ATTENTE_CONFIRMATION_BANCAIRE", "CHEQUE_REJETE"]
InvoiceSmsStatus = Literal["A_ENVOYER", "ENVOYE", "ECHEC", "LOCAL_LOG"]


class InvoiceRead(BaseModel):
    numero_facture: str
    visit_id: str
    patient_nom: str
    patient_tel: str
    moyen_paiement: str
    reference: str | None
    statut_document: InvoiceStatus
    mention_paiement: str | None
    download_url: str
    public_download_url: str
    sms_status: InvoiceSmsStatus
    sms_sent_at: datetime | None
    sms_error: str | None
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    items: list[InvoiceRead]
    total: int
