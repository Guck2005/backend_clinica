from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


VersementScope = Literal["UNIQUE", "CONSOLIDE"]
VersementStatus = Literal["EFFECTUE"]


class VersementCaisseRead(BaseModel):
    caisse_id: int
    montant_theorique_fcfa: int
    montant_theorique_especes_fcfa: int = 0
    montant_theorique_cheques_fcfa: int = 0


class VersementRead(BaseModel):
    versement_id: str
    date_versement: date
    scope: VersementScope
    caisse_ids: list[int]
    montant_theorique_fcfa: int
    montant_theorique_especes_fcfa: int
    montant_theorique_cheques_fcfa: int
    montant_compte_especes_fcfa: int
    montant_remis_cheques_fcfa: int
    montant_verse_fcfa: int
    ecart_fcfa: int
    note: str | None
    statut: VersementStatus
    declared_by_id: int
    justificatif_filename: str
    created_at: datetime


class VersementListResponse(BaseModel):
    items: list[VersementRead]
    total: int


class VersementTheoreticalCaisseRead(BaseModel):
    caisse_id: int
    montant_theorique_fcfa: int
    montant_theorique_especes_fcfa: int = 0
    montant_theorique_cheques_fcfa: int = 0


class VersementTheoreticalRead(BaseModel):
    date: date
    caisse_ids: list[int]
    montant_theorique_fcfa: int
    montant_theorique_especes_fcfa: int = 0
    montant_theorique_cheques_fcfa: int = 0
    per_caisse: list[VersementTheoreticalCaisseRead]
