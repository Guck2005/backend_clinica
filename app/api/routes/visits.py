from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.audit import log_audit
from app.core.phone import format_phone, normalize_phone
from app.db.session import get_db
from app.models.user import User
from app.models.visit import Visit
from app.schemas.visit import VisitCreate, VisitListResponse, VisitRead, VisitStatus


router = APIRouter(prefix="/visits", tags=["visits"])

def visit_to_read(visit: Visit) -> VisitRead:
    if visit.id_visite is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Visit identifier missing")
    return VisitRead(
        id=visit.id,
        id_visite=visit.id_visite,
        patient_nom=visit.patient_nom,
        patient_prenom=visit.patient_prenom,
        patient_tel=visit.patient_tel,
        motif_visite=visit.motif_visite,
        service_oriente=visit.service_oriente,
        agent_accueil_id=visit.agent_accueil_id,
        statut=visit.statut,
        created_at=visit.created_at,
        updated_at=visit.updated_at,
    )


def apply_visit_scope(query, user: User, today_only: bool):
    if user.role in {"admin", "superviseur", "auditeur", "caissier"}:
        return query
    if user.role == "accueil" and not today_only:
        return query.where(Visit.agent_accueil_id == user.id)
    return query


@router.get("", response_model=VisitListResponse)
def list_visits(
    search: str | None = None,
    telephone_exact: str | None = None,
    status_value: VisitStatus | None = Query(default=None, alias="status"),
    today_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisitListResponse:
    filters = []
    if search:
        pattern = f"%{search.strip()}%"
        normalized_search = normalize_phone(search)
        full_name = func.trim(Visit.patient_prenom + " " + Visit.patient_nom)
        reverse_full_name = func.trim(Visit.patient_nom + " " + Visit.patient_prenom)
        search_terms = [
            Visit.id_visite.ilike(pattern),
            Visit.patient_nom.ilike(pattern),
            Visit.patient_prenom.ilike(pattern),
            Visit.patient_tel.ilike(pattern),
            full_name.ilike(pattern),
            reverse_full_name.ilike(pattern),
        ]
        if normalized_search:
            search_terms.append(Visit.patient_tel_normalized.ilike(f"%{normalized_search}%"))
        filters.append(or_(*search_terms))
    if telephone_exact:
        filters.append(Visit.patient_tel_normalized == normalize_phone(telephone_exact))
    if status_value:
        filters.append(Visit.statut == status_value)
    if today_only:
        filters.append(func.date(Visit.created_at) == date.today().isoformat())

    base_query = select(Visit)
    count_query = select(func.count(Visit.id))
    for condition in filters:
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)

    base_query = apply_visit_scope(base_query, user, today_only)
    count_query = apply_visit_scope(count_query, user, today_only)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        base_query
        .order_by(Visit.created_at.desc(), Visit.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return VisitListResponse(
        items=[visit_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{id_visite}", response_model=VisitRead)
def get_visit(
    id_visite: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisitRead:
    visit = db.scalar(select(Visit).where(Visit.id_visite == id_visite.upper().strip()))
    if visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    if user.role == "accueil" and visit.agent_accueil_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return visit_to_read(visit)


@router.post("", response_model=VisitRead, status_code=status.HTTP_201_CREATED)
def create_visit(
    payload: VisitCreate,
    user: User = Depends(require_roles("accueil", "admin")),
    db: Session = Depends(get_db),
) -> VisitRead:
    normalized_phone = normalize_phone(payload.patient_tel)
    visit = Visit(
        patient_nom=payload.patient_nom.strip(),
        patient_prenom=payload.patient_prenom.strip(),
        patient_tel=format_phone(payload.patient_tel),
        patient_tel_normalized=normalized_phone,
        motif_visite=payload.motif_visite.strip(),
        service_oriente=payload.service_oriente.strip(),
        agent_accueil_id=user.id,
        statut="EN_ATTENTE",
    )
    db.add(visit)
    db.flush()
    visit.id_visite = f"VIS-{visit.id:04d}"
    log_audit(
        db,
        action_code="VISIT_CREATED",
        action_label="Creation dossier accueil",
        entity_type="VISIT",
        entity_id=visit.id_visite,
        actor=user,
        detail={
            "patient_nom": visit.patient_nom,
            "patient_prenom": visit.patient_prenom,
            "service_oriente": visit.service_oriente,
        },
    )
    db.commit()
    db.refresh(visit)
    return visit_to_read(visit)


@router.post("/{id_visite}/open-cashier", response_model=VisitRead)
def open_visit_in_cashier(
    id_visite: str,
    user: User = Depends(require_roles("caissier", "admin")),
    db: Session = Depends(get_db),
) -> VisitRead:
    visit = db.scalar(select(Visit).where(Visit.id_visite == id_visite.upper().strip()))
    if visit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visit not found")
    if visit.statut == "EN_ATTENTE":
        visit.statut = "EN_CAISSE"
        log_audit(
            db,
            action_code="VISIT_OPENED_CASHIER",
            action_label="Ouverture dossier en caisse",
            entity_type="VISIT",
            entity_id=visit.id_visite or str(visit.id),
            actor=user,
            caisse_id=user.caisse_id,
        )
        db.commit()
        db.refresh(visit)
    return visit_to_read(visit)
