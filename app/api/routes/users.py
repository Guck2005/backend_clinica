from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.audit import log_audit
from app.core.security import hash_password
from app.db.session import get_db
from app.models.caisse import Caisse
from app.models.user import User
from app.schemas.admin_user import AdminUserCreate, AdminUserListResponse, AdminUserRead, AdminUserUpdate, UserRole


router = APIRouter(prefix="/users", tags=["users"])


def user_to_read(user: User) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        nom=user.nom,
        identifiant=user.identifiant,
        role=user.role,
        actif=user.actif,
        caisse_id=user.caisse_id,
        caisse_nom=user.caisse.nom if user.caisse else None,
        created_at=user.created_at,
    )


def ensure_unique_identifiant(db: Session, identifiant: str, user_id: int | None = None) -> None:
    clauses = [User.identifiant == identifiant]
    if user_id is not None:
        clauses.append(User.id != user_id)
    existing = db.scalar(select(User).where(*clauses))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cet identifiant existe deja.")


def resolve_caisse_assignment(
    db: Session,
    role: UserRole,
    caisse_id: int | None,
    must_be_active: bool,
) -> int | None:
    if role != "caissier":
        return None
    if caisse_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Une caisse active est obligatoire pour un caissier.",
        )
    caisse = db.get(Caisse, caisse_id)
    if caisse is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Caisse introuvable.")
    if must_be_active and not caisse.actif:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le caissier doit etre affecte a une caisse active.",
        )
    return caisse.id


@router.get("", response_model=AdminUserListResponse)
def list_users(
    search: str | None = None,
    role: UserRole | None = None,
    actif: bool | None = None,
    caisse_id: int | None = Query(default=None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserListResponse:
    query = select(User).order_by(User.nom.asc(), User.id.asc())
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(User.nom.ilike(pattern), User.identifiant.ilike(pattern)))
    if role is not None:
        query = query.where(User.role == role)
    if actif is not None:
        query = query.where(User.actif.is_(actif))
    if caisse_id is not None:
        query = query.where(User.caisse_id == caisse_id)
    items = db.scalars(query).all()
    return AdminUserListResponse(items=[user_to_read(item) for item in items], total=len(items))


@router.post("", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserRead:
    nom = payload.nom.strip()
    identifiant = payload.identifiant.strip()
    if not nom or not identifiant:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le nom et l'identifiant sont obligatoires.",
        )
    ensure_unique_identifiant(db, identifiant)
    caisse_id = resolve_caisse_assignment(
        db,
        role=payload.role,
        caisse_id=payload.caisse_id,
        must_be_active=payload.actif,
    )
    user = User(
        nom=nom,
        identifiant=identifiant,
        password_hash=hash_password(payload.mot_de_passe),
        role=payload.role,
        actif=payload.actif,
        caisse_id=caisse_id,
    )
    db.add(user)
    db.flush()
    log_audit(
        db,
        action_code="USER_CREATED",
        action_label="Creation de compte",
        entity_type="USER",
        entity_id=str(user.id),
        actor=admin,
        detail={"role": user.role, "identifiant": user.identifiant, "caisse_id": user.caisse_id},
    )
    db.commit()
    db.refresh(user)
    return user_to_read(user)


@router.patch("/{user_id}", response_model=AdminUserRead)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserRead:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")

    next_nom = payload.nom.strip() if payload.nom is not None else user.nom
    next_identifiant = payload.identifiant.strip() if payload.identifiant is not None else user.identifiant
    next_role = payload.role or user.role
    next_actif = payload.actif if payload.actif is not None else user.actif
    next_caisse_input = payload.caisse_id if payload.caisse_id is not None else user.caisse_id

    if not next_nom or not next_identifiant:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le nom et l'identifiant sont obligatoires.",
        )

    ensure_unique_identifiant(db, next_identifiant, user_id=user.id)
    next_caisse_id = resolve_caisse_assignment(
        db,
        role=next_role,
        caisse_id=next_caisse_input,
        must_be_active=next_actif,
    )

    user.nom = next_nom
    user.identifiant = next_identifiant
    user.role = next_role
    user.actif = next_actif
    user.caisse_id = next_caisse_id
    log_audit(
        db,
        action_code="USER_UPDATED",
        action_label="Modification de compte",
        entity_type="USER",
        entity_id=str(user.id),
        actor=admin,
        detail={"role": user.role, "actif": user.actif, "caisse_id": user.caisse_id},
    )

    db.commit()
    db.refresh(user)
    return user_to_read(user)


@router.patch("/{user_id}/deactivate", response_model=AdminUserRead)
def deactivate_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AdminUserRead:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte introuvable.")
    if user.actif:
        user.actif = False
        log_audit(
            db,
            action_code="USER_DEACTIVATED",
            action_label="Desactivation de compte",
            entity_type="USER",
            entity_id=str(user.id),
            actor=admin,
            detail={"identifiant": user.identifiant},
        )
        db.commit()
        db.refresh(user)
    return user_to_read(user)
