from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.audit import log_audit
from app.db.session import get_db
from app.models.catalogue import CatalogueItem, CatalogueTariffHistory
from app.models.user import User
from app.schemas.catalogue import (
    CatalogueItemCreate,
    CatalogueItemRead,
    CatalogueItemUpdate,
    CatalogueListResponse,
    TariffHistoryRead,
)


router = APIRouter(prefix="/catalogue", tags=["catalogue"])


def item_to_read(item: CatalogueItem) -> CatalogueItemRead:
    return CatalogueItemRead(
        id=item.id,
        code_element=item.code_element,
        code_labo=item.code_labo,
        type=item.type,
        nom=item.nom,
        service=item.service,
        montant_fcfa=item.montant_fcfa,
        hopital_id=item.hopital_id,
        actif=item.actif,
        metadata=item.metadata_json or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=CatalogueListResponse)
def list_catalogue(
    search: str | None = None,
    type: str | None = None,
    service: str | None = None,
    actif: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogueListResponse:
    filters = []
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                CatalogueItem.nom.ilike(pattern),
                CatalogueItem.type.ilike(pattern),
                CatalogueItem.service.ilike(pattern),
                CatalogueItem.code_element.ilike(pattern),
                CatalogueItem.code_labo.ilike(pattern),
            )
        )
    if type:
        filters.append(CatalogueItem.type == type)
    if service:
        filters.append(CatalogueItem.service == service)
    if actif is not None:
        filters.append(CatalogueItem.actif == actif)

    base_query = select(CatalogueItem)
    count_query = select(func.count(CatalogueItem.id))
    for condition in filters:
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        base_query
        .order_by(CatalogueItem.nom.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CatalogueListResponse(
        items=[item_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{item_id}", response_model=CatalogueItemRead)
def get_catalogue_item(
    item_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CatalogueItemRead:
    item = db.get(CatalogueItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalogue item not found")
    return item_to_read(item)


@router.post("", response_model=CatalogueItemRead, status_code=status.HTTP_201_CREATED)
def create_catalogue_item(
    payload: CatalogueItemCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CatalogueItemRead:
    existing = db.scalar(select(CatalogueItem).where(CatalogueItem.code_element == payload.code_element))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="code_element already exists")

    item = CatalogueItem(
        code_element=payload.code_element.strip(),
        code_labo=payload.code_labo.strip() if payload.code_labo else None,
        type=payload.type.strip(),
        nom=payload.nom.strip(),
        service=payload.service.strip(),
        montant_fcfa=payload.montant_fcfa,
        hopital_id=payload.hopital_id.strip(),
        actif=payload.actif,
        metadata_json=payload.metadata,
    )
    db.add(item)
    db.flush()
    log_audit(
        db,
        action_code="CATALOGUE_CREATED",
        action_label="Creation d'element catalogue",
        entity_type="CATALOGUE_ITEM",
        entity_id=str(item.id),
        actor=admin,
        detail={"code_element": item.code_element, "nom": item.nom, "montant_fcfa": item.montant_fcfa},
    )
    db.commit()
    db.refresh(item)
    return item_to_read(item)


@router.patch("/{item_id}", response_model=CatalogueItemRead)
def update_catalogue_item(
    item_id: int,
    payload: CatalogueItemUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CatalogueItemRead:
    item = db.get(CatalogueItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalogue item not found")

    data = payload.model_dump(exclude_unset=True)
    old_amount = item.montant_fcfa

    for field in ["code_labo", "type", "nom", "service", "montant_fcfa", "hopital_id", "actif"]:
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(item, field, value)
    if "metadata" in data:
        item.metadata_json = data["metadata"] or {}

    if "montant_fcfa" in data and item.montant_fcfa != old_amount:
        db.add(
            CatalogueTariffHistory(
                catalogue_item_id=item.id,
                ancien_montant_fcfa=old_amount,
                nouveau_montant_fcfa=item.montant_fcfa,
                auteur_id=user.id,
            )
        )

    log_audit(
        db,
        action_code="CATALOGUE_UPDATED",
        action_label="Modification d'element catalogue",
        entity_type="CATALOGUE_ITEM",
        entity_id=str(item.id),
        actor=user,
        detail={"code_element": item.code_element, "montant_fcfa": item.montant_fcfa, "actif": item.actif},
    )
    db.commit()
    db.refresh(item)
    return item_to_read(item)


@router.patch("/{item_id}/deactivate", response_model=CatalogueItemRead)
def deactivate_catalogue_item(
    item_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CatalogueItemRead:
    item = db.get(CatalogueItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalogue item not found")
    item.actif = False
    log_audit(
        db,
        action_code="CATALOGUE_DEACTIVATED",
        action_label="Desactivation d'element catalogue",
        entity_type="CATALOGUE_ITEM",
        entity_id=str(item.id),
        actor=admin,
        detail={"code_element": item.code_element},
    )
    db.commit()
    db.refresh(item)
    return item_to_read(item)


@router.get("/{item_id}/tariff-history", response_model=list[TariffHistoryRead])
def get_tariff_history(
    item_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[TariffHistoryRead]:
    item = db.get(CatalogueItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalogue item not found")

    rows = db.execute(
        select(CatalogueTariffHistory, User.nom)
        .join(User, User.id == CatalogueTariffHistory.auteur_id, isouter=True)
        .where(CatalogueTariffHistory.catalogue_item_id == item_id)
        .order_by(CatalogueTariffHistory.created_at.desc())
    ).all()
    return [
        TariffHistoryRead(
            id=history.id,
            catalogue_item_id=history.catalogue_item_id,
            ancien_montant_fcfa=history.ancien_montant_fcfa,
            nouveau_montant_fcfa=history.nouveau_montant_fcfa,
            auteur_id=history.auteur_id,
            auteur_nom=auteur_nom,
            created_at=history.created_at,
        )
        for history, auteur_nom in rows
    ]
