from datetime import datetime
from typing import Literal

from pydantic import BaseModel


UserRole = Literal["admin", "caissier", "superviseur", "accueil", "auditeur"]


class AdminUserCreate(BaseModel):
    nom: str
    identifiant: str
    mot_de_passe: str
    role: UserRole
    caisse_id: int | None = None
    actif: bool = True


class AdminUserUpdate(BaseModel):
    nom: str | None = None
    identifiant: str | None = None
    role: UserRole | None = None
    caisse_id: int | None = None
    actif: bool | None = None


class AdminUserRead(BaseModel):
    id: int
    nom: str
    identifiant: str
    role: UserRole
    actif: bool
    caisse_id: int | None
    caisse_nom: str | None
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserRead]
    total: int
