from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_roles
from app.core.audit import log_audit
from app.db.session import get_db
from app.models.caisse import Caisse
from app.models.user import User
from app.schemas.caisse import CaisseCreate, CaisseListResponse, CaisseRead, CaisseUpdate


router = APIRouter(prefix="/caisses", tags=["caisses"])


def caisse_to_read(caisse: Caisse) -> CaisseRead:
    return CaisseRead(
        id=caisse.id,
        nom=caisse.nom,
        actif=caisse.actif,
        created_at=caisse.created_at,
        updated_at=caisse.updated_at,
    )


def ensure_caisse_can_be_deactivated(db: Session, caisse: Caisse) -> None:
    active_cashiers = db.scalar(
        select(func.count(User.id)).where(
            User.role == "caissier",
            User.actif.is_(True),
            User.caisse_id == caisse.id,
        )
    ) or 0
    if active_cashiers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette caisse a encore des caissiers actifs affectes.",
        )


@router.get("", response_model=CaisseListResponse)
def list_caisses(
    _: User = Depends(require_roles("admin", "superviseur")),
    db: Session = Depends(get_db),
) -> CaisseListResponse:
    items = db.scalars(select(Caisse).order_by(Caisse.nom.asc(), Caisse.id.asc())).all()
    return CaisseListResponse(items=[caisse_to_read(item) for item in items], total=len(items))


@router.post("", response_model=CaisseRead, status_code=status.HTTP_201_CREATED)
def create_caisse(
    payload: CaisseCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CaisseRead:
    nom = payload.nom.strip()
    if not nom:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Le nom est obligatoire.")
    existing = db.scalar(select(Caisse).where(func.lower(Caisse.nom) == nom.lower()))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Une caisse avec ce nom existe deja.")
    caisse = Caisse(nom=nom, actif=payload.actif)
    db.add(caisse)
    db.flush()
    log_audit(
        db,
        action_code="CAISSE_CREATED",
        action_label="Creation de caisse",
        entity_type="CAISSE",
        entity_id=str(caisse.id),
        actor=admin,
        detail={"nom": caisse.nom, "actif": caisse.actif},
    )
    db.commit()
    db.refresh(caisse)
    return caisse_to_read(caisse)


@router.patch("/{caisse_id}", response_model=CaisseRead)
def update_caisse(
    caisse_id: int,
    payload: CaisseUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CaisseRead:
    caisse = db.get(Caisse, caisse_id)
    if caisse is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caisse introuvable.")

    if payload.nom is not None:
        nom = payload.nom.strip()
        if not nom:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Le nom est obligatoire.")
        existing = db.scalar(
            select(Caisse).where(
                func.lower(Caisse.nom) == nom.lower(),
                Caisse.id != caisse.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Une caisse avec ce nom existe deja.")
        caisse.nom = nom

    if payload.actif is not None:
        if not payload.actif and caisse.actif:
            ensure_caisse_can_be_deactivated(db, caisse)
        caisse.actif = payload.actif

    log_audit(
        db,
        action_code="CAISSE_UPDATED",
        action_label="Modification de caisse",
        entity_type="CAISSE",
        entity_id=str(caisse.id),
        actor=admin,
        detail={"nom": caisse.nom, "actif": caisse.actif},
    )
    db.commit()
    db.refresh(caisse)
    return caisse_to_read(caisse)


@router.patch("/{caisse_id}/deactivate", response_model=CaisseRead)
def deactivate_caisse(
    caisse_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CaisseRead:
    caisse = db.get(Caisse, caisse_id)
    if caisse is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caisse introuvable.")
    if caisse.actif:
        ensure_caisse_can_be_deactivated(db, caisse)
        caisse.actif = False
        log_audit(
            db,
            action_code="CAISSE_DEACTIVATED",
            action_label="Desactivation de caisse",
            entity_type="CAISSE",
            entity_id=str(caisse.id),
            actor=admin,
            detail={"nom": caisse.nom},
        )
        db.commit()
        db.refresh(caisse)
    return caisse_to_read(caisse)
