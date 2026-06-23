from datetime import datetime
from typing import Literal

from pydantic import BaseModel


ChequePaymentStatus = Literal["RECU", "ENCAISSE", "REJETE"]


class ChequePaymentRead(BaseModel):
    payment_id: int
    transaction_id: int
    id_visite: str
    caisse_id: int | None
    caisse_nom: str | None
    patient_nom: str
    patient_tel: str
    montant_fcfa: int
    statut: ChequePaymentStatus
    cheque_numero: str
    cheque_banque: str
    cheque_titulaire: str
    invoice_number: str | None
    created_at: datetime
    updated_at: datetime


class ChequePaymentListResponse(BaseModel):
    items: list[ChequePaymentRead]
    total: int


class ChequePaymentStatusUpdate(BaseModel):
    statut: Literal["ENCAISSE", "REJETE"]
