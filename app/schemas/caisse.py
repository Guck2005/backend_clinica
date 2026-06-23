from datetime import datetime

from pydantic import BaseModel


class CaisseCreate(BaseModel):
    nom: str
    actif: bool = True


class CaisseUpdate(BaseModel):
    nom: str | None = None
    actif: bool | None = None


class CaisseRead(BaseModel):
    id: int
    nom: str
    actif: bool
    created_at: datetime
    updated_at: datetime


class CaisseListResponse(BaseModel):
    items: list[CaisseRead]
    total: int
