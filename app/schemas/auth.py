from pydantic import BaseModel

from app.schemas.admin_user import UserRole


class LoginRequest(BaseModel):
    identifiant: str
    mot_de_passe: str


class UserRead(BaseModel):
    id: int
    nom: str
    identifiant: str
    role: UserRole
    actif: bool
    caisse_id: int | None
    caisse_nom: str | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
