from datetime import datetime
from typing import Literal

from pydantic import BaseModel


VisitStatus = Literal["EN_ATTENTE", "EN_CAISSE", "SOLDE", "PARTIELLEMENT_SOLDE"]


class VisitCreate(BaseModel):
    patient_nom: str
    patient_prenom: str
    patient_tel: str
    motif_visite: str
    service_oriente: str


class VisitRead(BaseModel):
    id: int
    id_visite: str
    patient_nom: str
    patient_prenom: str
    patient_tel: str
    motif_visite: str
    service_oriente: str
    agent_accueil_id: int
    statut: VisitStatus
    created_at: datetime
    updated_at: datetime


class VisitListResponse(BaseModel):
    items: list[VisitRead]
    total: int
    page: int
    page_size: int
