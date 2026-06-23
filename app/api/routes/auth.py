from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import log_audit
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserRead


router = APIRouter(tags=["auth"])


def user_to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        nom=user.nom,
        identifiant=user.identifiant,
        role=user.role,
        actif=user.actif,
        caisse_id=user.caisse_id,
        caisse_nom=user.caisse.nom if user.caisse else None,
    )


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.identifiant == payload.identifiant))
    if user is None or not verify_password(payload.mot_de_passe, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.actif:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce compte est desactive.")
    if user.role == "caissier" and (user.caisse is None or not user.caisse.actif):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce caissier n'a pas de caisse active affectee.",
        )
    token = create_access_token(str(user.id), user.role)
    log_audit(
        db,
        action_code="AUTH_LOGIN",
        action_label="Connexion reussie",
        entity_type="USER",
        entity_id=str(user.id),
        actor=user,
        detail={"identifiant": user.identifiant},
    )
    db.commit()
    return TokenResponse(access_token=token, user=user_to_read(user))


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return user_to_read(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    log_audit(
        db,
        action_code="AUTH_LOGOUT",
        action_label="Deconnexion",
        entity_type="USER",
        entity_id=str(user.id),
        actor=user,
    )
    db.commit()
