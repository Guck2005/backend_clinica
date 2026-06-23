from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_roles
from app.core.alerting import upsert_named_alert
from app.core.audit import log_audit
from app.db.session import get_db
from app.models.caisse import Caisse
from app.models.transaction import Payment, Transaction
from app.models.user import User
from app.models.versement import Versement, VersementCaisse
from app.schemas.versement import (
    VersementListResponse,
    VersementRead,
    VersementTheoreticalCaisseRead,
    VersementTheoreticalRead,
)


router = APIRouter(prefix="/versements", tags=["versements"])


def server_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def resolve_caisse_ids(db: Session, caisse_ids: list[int] | None) -> list[int]:
    if caisse_ids:
        existing = db.scalars(select(Caisse).where(Caisse.id.in_(caisse_ids), Caisse.actif.is_(True))).all()
        found_ids = sorted({caisse.id for caisse in existing})
        if len(found_ids) != len(set(caisse_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Une ou plusieurs caisses selectionnees sont introuvables ou inactives.",
            )
        return found_ids

    return db.scalars(select(Caisse.id).where(Caisse.actif.is_(True)).order_by(Caisse.id.asc())).all()


def compute_theoretical_by_caisse(db: Session, target_date: date, caisse_ids: list[int]) -> list[VersementTheoreticalCaisseRead]:
    if not caisse_ids:
        return []

    start, end = server_day_bounds(target_date)
    rows = db.execute(
        select(
            Transaction.caisse_id,
            Payment.moyen_paiement,
            func.coalesce(func.sum(Payment.montant_fcfa), 0),
        )
        .join(Transaction, Transaction.id == Payment.transaction_id)
        .where(
            Transaction.caisse_id.in_(caisse_ids),
            Payment.created_at >= start,
            Payment.created_at < end,
            or_(
                and_(Payment.moyen_paiement == "ESPECES", Payment.statut == "CONFIRME"),
                and_(Payment.moyen_paiement == "CHEQUE", Payment.statut.in_(("RECU", "ENCAISSE"))),
            ),
        )
        .group_by(Transaction.caisse_id, Payment.moyen_paiement)
    ).all()
    amount_by_caisse: dict[int, dict[str, int]] = {}
    for caisse_id, moyen_paiement, amount in rows:
        if caisse_id is None:
            continue
        bucket = amount_by_caisse.setdefault(caisse_id, {"ESPECES": 0, "CHEQUE": 0})
        bucket[str(moyen_paiement)] = int(amount or 0)
    return [
        VersementTheoreticalCaisseRead(
            caisse_id=caisse_id,
            montant_theorique_fcfa=sum(amount_by_caisse.get(caisse_id, {"ESPECES": 0, "CHEQUE": 0}).values()),
            montant_theorique_especes_fcfa=amount_by_caisse.get(caisse_id, {"ESPECES": 0}).get("ESPECES", 0),
            montant_theorique_cheques_fcfa=amount_by_caisse.get(caisse_id, {"CHEQUE": 0}).get("CHEQUE", 0),
        )
        for caisse_id in caisse_ids
    ]


def versement_to_read(versement: Versement) -> VersementRead:
    return VersementRead(
        versement_id=versement.versement_id,
        date_versement=versement.date_versement,
        scope=versement.scope,  # type: ignore[arg-type]
        caisse_ids=[item.caisse_id for item in versement.caisses],
        montant_theorique_fcfa=versement.montant_theorique_fcfa,
        montant_theorique_especes_fcfa=versement.montant_theorique_especes_fcfa,
        montant_theorique_cheques_fcfa=versement.montant_theorique_cheques_fcfa,
        montant_compte_especes_fcfa=versement.montant_compte_especes_fcfa,
        montant_remis_cheques_fcfa=versement.montant_remis_cheques_fcfa,
        montant_verse_fcfa=versement.montant_verse_fcfa,
        ecart_fcfa=versement.ecart_fcfa,
        note=versement.note,
        statut=versement.statut,  # type: ignore[arg-type]
        declared_by_id=versement.declared_by_id,
        justificatif_filename=versement.justificatif_filename,
        created_at=versement.created_at,
    )


@router.get("/theoretical", response_model=VersementTheoreticalRead)
def get_theoretical_versement(
    date_value: date | None = Query(default=None, alias="date"),
    caisse_ids: str | None = None,
    _: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> VersementTheoreticalRead:
    target_date = date_value or datetime.now(timezone.utc).date()
    requested_ids = [int(value) for value in caisse_ids.split(",") if value.strip()] if caisse_ids else None
    selected_caisse_ids = resolve_caisse_ids(db, requested_ids)
    per_caisse = compute_theoretical_by_caisse(db, target_date, selected_caisse_ids)
    return VersementTheoreticalRead(
        date=target_date,
        caisse_ids=selected_caisse_ids,
        montant_theorique_fcfa=sum(item.montant_theorique_fcfa for item in per_caisse),
        montant_theorique_especes_fcfa=sum(item.montant_theorique_especes_fcfa for item in per_caisse),
        montant_theorique_cheques_fcfa=sum(item.montant_theorique_cheques_fcfa for item in per_caisse),
        per_caisse=per_caisse,
    )


@router.post("", response_model=VersementRead, status_code=status.HTTP_201_CREATED)
async def create_versement(
    date_versement: date = Form(...),
    scope: str = Form(...),
    caisse_ids: list[int] = Form(...),
    montant_compte_especes_fcfa: int | None = Form(default=None),
    montant_remis_cheques_fcfa: int | None = Form(default=None),
    montant_verse_fcfa: int | None = Form(default=None),
    note: str | None = Form(default=None),
    justificatif: UploadFile = File(...),
    user: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> VersementRead:
    normalized_scope = scope.upper().strip()
    if normalized_scope not in {"UNIQUE", "CONSOLIDE"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Scope de versement invalide.")

    selected_caisse_ids = resolve_caisse_ids(db, caisse_ids)
    if normalized_scope == "UNIQUE" and len(selected_caisse_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un versement UNIQUE doit cibler exactement une caisse.",
        )
    if normalized_scope == "CONSOLIDE" and len(selected_caisse_ids) < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un versement CONSOLIDE doit cibler au moins une caisse.",
        )
    montant_compte_especes = montant_compte_especes_fcfa
    montant_remis_cheques = montant_remis_cheques_fcfa
    if montant_compte_especes is None and montant_remis_cheques is None and montant_verse_fcfa is not None:
        montant_compte_especes = montant_verse_fcfa
        montant_remis_cheques = 0
    if montant_compte_especes is None or montant_remis_cheques is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Les montants especes et cheques sont obligatoires.",
        )
    if montant_compte_especes < 0 or montant_remis_cheques < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Les montants saisis sont invalides.")

    justificatif_bytes = await justificatif.read()
    if not justificatif_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le justificatif de versement est obligatoire.",
        )

    per_caisse = compute_theoretical_by_caisse(db, date_versement, selected_caisse_ids)
    montant_theorique_fcfa = sum(item.montant_theorique_fcfa for item in per_caisse)
    montant_theorique_especes_fcfa = sum(item.montant_theorique_especes_fcfa for item in per_caisse)
    montant_theorique_cheques_fcfa = sum(item.montant_theorique_cheques_fcfa for item in per_caisse)
    montant_verse_fcfa = montant_compte_especes + montant_remis_cheques
    ecart_especes_fcfa = montant_compte_especes - montant_theorique_especes_fcfa
    ecart_fcfa = montant_verse_fcfa - montant_theorique_fcfa

    versement = Versement(
        versement_id="PENDING",
        date_versement=date_versement,
        scope=normalized_scope,
        montant_theorique_fcfa=montant_theorique_fcfa,
        montant_theorique_especes_fcfa=montant_theorique_especes_fcfa,
        montant_theorique_cheques_fcfa=montant_theorique_cheques_fcfa,
        montant_compte_especes_fcfa=montant_compte_especes,
        montant_remis_cheques_fcfa=montant_remis_cheques,
        montant_verse_fcfa=montant_verse_fcfa,
        ecart_fcfa=ecart_fcfa,
        note=(note or "").strip() or None,
        justificatif_filename=justificatif.filename or "justificatif.bin",
        justificatif_content_type=justificatif.content_type or "application/octet-stream",
        justificatif_bytes=justificatif_bytes,
        declared_by_id=user.id,
        statut="EFFECTUE",
        caisses=[
            VersementCaisse(
                caisse_id=item.caisse_id,
                montant_theorique_fcfa=item.montant_theorique_fcfa,
            )
            for item in per_caisse
        ],
    )
    db.add(versement)
    db.flush()
    versement.versement_id = f"VRS-{versement.id:06d}"

    if ecart_especes_fcfa != 0:
        upsert_named_alert(
            db,
            rule_code="ECART_ESPECES_CAISSE",
            gravite="haute" if abs(ecart_especes_fcfa) <= 10000 else "critique",
            message=(
                f"Ecart d'especes constate sur {versement.versement_id}: "
                f"{ecart_especes_fcfa:+d} FCFA entre le compte physique et le theorique especes."
            ),
            caisse_id=selected_caisse_ids[0] if len(selected_caisse_ids) == 1 else None,
            source_type="VERSEMENT_ESPECES",
            source_id=versement.versement_id,
            impact_amount_fcfa=ecart_especes_fcfa,
            details={
                "constat": "Le compte d'especes differe du theorique de caisse.",
                "pieces_concernees": versement.versement_id,
                "recommandation": "Verifier le fond de caisse, les remises manuelles et les ecarts de comptage.",
            },
            actor=user,
        )

    if ecart_fcfa != 0:
        upsert_named_alert(
            db,
            rule_code="ECART_VERSEMENT_BANCAIRE",
            gravite="haute" if abs(ecart_fcfa) <= 10000 else "critique",
            message=(
                f"Ecart de versement bancaire detecte sur {versement.versement_id}: "
                f"{ecart_fcfa:+d} FCFA par rapport au total theorique attendu."
            ),
            caisse_id=selected_caisse_ids[0] if len(selected_caisse_ids) == 1 else None,
            source_type="VERSEMENT",
            source_id=versement.versement_id,
            impact_amount_fcfa=ecart_fcfa,
            details={
                "constat": "Le montant total remis a la banque differe du theorique especes + cheques.",
                "pieces_concernees": versement.versement_id,
                "recommandation": "Verifier le bordereau bancaire, les montants especes, les cheques remis et les justificatifs joints.",
            },
            actor=user,
        )

    log_audit(
        db,
        action_code="VERSEMENT_CREATED",
        action_label="Creation de versement bancaire",
        entity_type="VERSEMENT",
        entity_id=versement.versement_id,
        actor=user,
        detail={
            "scope": versement.scope,
            "montant_compte_especes_fcfa": montant_compte_especes,
            "montant_remis_cheques_fcfa": montant_remis_cheques,
            "montant_verse_fcfa": montant_verse_fcfa,
        },
    )
    db.commit()
    db.refresh(versement)
    return versement_to_read(versement)


@router.get("", response_model=VersementListResponse)
def list_versements(
    date_from: date | None = None,
    date_to: date | None = None,
    caisse_id: int | None = None,
    scope: str | None = None,
    page: int = 1,
    page_size: int = 50,
    _: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> VersementListResponse:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 200)
    versements = db.scalars(
        select(Versement)
        .options(selectinload(Versement.caisses))
        .order_by(Versement.date_versement.desc(), Versement.id.desc())
    ).all()

    filtered = []
    for versement in versements:
        if date_from and versement.date_versement < date_from:
            continue
        if date_to and versement.date_versement > date_to:
            continue
        if scope and versement.scope != scope.upper().strip():
            continue
        if caisse_id is not None and all(item.caisse_id != caisse_id for item in versement.caisses):
            continue
        filtered.append(versement)

    page_items = filtered[(safe_page - 1) * safe_page_size : safe_page * safe_page_size]
    return VersementListResponse(items=[versement_to_read(item) for item in page_items], total=len(filtered))


@router.get("/{versement_id}/justificatif")
def download_justificatif(
    versement_id: str,
    _: User = Depends(require_roles("superviseur", "admin")),
    db: Session = Depends(get_db),
) -> Response:
    versement = db.scalar(select(Versement).where(Versement.versement_id == versement_id.upper().strip()))
    if versement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versement introuvable.")
    return Response(
        content=versement.justificatif_bytes,
        media_type=versement.justificatif_content_type,
        headers={"Content-Disposition": f'inline; filename="{versement.justificatif_filename}"'},
    )
