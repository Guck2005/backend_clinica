from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CatalogueItemCreate(BaseModel):
    code_element: str
    code_labo: str | None = None
    type: str = "Analyse"
    nom: str
    service: str = "Laboratoire"
    montant_fcfa: int = Field(ge=0)
    hopital_id: str = "HSJ-229"
    actif: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CatalogueItemUpdate(BaseModel):
    code_labo: str | None = None
    type: str | None = None
    nom: str | None = None
    service: str | None = None
    montant_fcfa: int | None = Field(default=None, ge=0)
    hopital_id: str | None = None
    actif: bool | None = None
    metadata: dict[str, Any] | None = None


class CatalogueItemRead(BaseModel):
    id: int
    code_element: str
    code_labo: str | None
    type: str
    nom: str
    service: str
    montant_fcfa: int
    hopital_id: str
    actif: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CatalogueListResponse(BaseModel):
    items: list[CatalogueItemRead]
    total: int
    page: int
    page_size: int


class TariffHistoryRead(BaseModel):
    id: int
    catalogue_item_id: int
    ancien_montant_fcfa: int
    nouveau_montant_fcfa: int
    auteur_id: int | None
    auteur_nom: str | None = None
    created_at: datetime
