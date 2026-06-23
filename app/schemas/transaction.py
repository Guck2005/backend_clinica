from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TransactionStatus = Literal["EN_ATTENTE", "ECHOUE", "SOLDE", "PARTIELLEMENT_SOLDE"]
PaymentMethod = Literal["ESPECES", "CHEQUE", "MOBILE_MONEY"]
PaymentStatus = Literal["EN_ATTENTE", "CONFIRME", "ECHOUE", "RECU", "ENCAISSE", "REJETE"]
OperatorCode = Literal["MTN", "MOOV", "CELTIIS"]


class TransactionLineCreate(BaseModel):
    catalogue_item_id: int
    quantite: int = Field(ge=1)
    payable: bool = True
    motif_non_honore: str | None = None


class PaymentCreate(BaseModel):
    moyen_paiement: PaymentMethod
    montant_recu_fcfa: int | None = Field(default=None, ge=0)
    reference_paiement: str | None = None
    telephone_paiement: str | None = None
    cheque_numero: str | None = None
    cheque_banque: str | None = None
    cheque_titulaire: str | None = None


class TransactionCreate(BaseModel):
    id_visite: str
    lignes: list[TransactionLineCreate]
    paiement: PaymentCreate


class MobileMoneyRetryRequest(BaseModel):
    telephone_paiement: str | None = None


class TransactionLineRead(BaseModel):
    id: int
    catalogue_item_id: int
    code_element_snapshot: str
    nom_snapshot: str
    type_snapshot: str
    service_snapshot: str
    quantite: int
    prix_unitaire_fcfa: int
    montant_ligne_fcfa: int
    payable: bool
    motif_non_honore: str | None
    created_at: datetime


class PaymentRead(BaseModel):
    id: int
    attempt_no: int
    moyen_paiement: PaymentMethod
    statut: PaymentStatus
    montant_fcfa: int
    provider: str | None
    provider_attempt_id: str | None
    provider_status: str | None
    operator_code: OperatorCode | None
    reference_paiement: str | None
    provider_error_code: str | None
    provider_mode: str | None
    provider_amount_debited_fcfa: int | None
    provider_fees_fcfa: int | None
    montant_recu_fcfa: int | None
    monnaie_rendue_fcfa: int | None
    telephone_paiement: str | None
    cheque_numero: str | None
    cheque_banque: str | None
    cheque_titulaire: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    failed_at: datetime | None


class TransactionRead(BaseModel):
    id: int
    id_visite: str
    patient_nom: str
    patient_tel: str
    caisse_id: int | None
    caissier_id: int
    statut: TransactionStatus
    montant_total_fcfa: int
    montant_encaisse_fcfa: int
    invoice_number: str | None = None
    invoice_status: str | None = None
    can_reopen_in_cashier: bool
    blocking_reason: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[TransactionLineRead]
    payment: PaymentRead


class TransactionSummaryRead(BaseModel):
    encaisse_fcfa: int
    especes_fcfa: int
    cheques_fcfa: int
    momo_fcfa: int


class TransactionListResponse(BaseModel):
    items: list[TransactionRead]
    total: int
    summary: TransactionSummaryRead
