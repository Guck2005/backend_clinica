from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.backups import backup_supported, get_or_create_backup_settings, run_backup
from app.db.session import get_db
from app.models.backup import BackupRun
from app.models.user import User
from app.schemas.backup import BackupRunListResponse, BackupRunRead, BackupSettingsRead, BackupSettingsUpdate


router = APIRouter(prefix="/admin/backups", tags=["backups"])


def settings_to_read(setting, db: Session) -> BackupSettingsRead:
    supported, reason = backup_supported(db)
    return BackupSettingsRead(
        enabled=setting.enabled,
        frequency_minutes=setting.frequency_minutes,
        target_directory=setting.target_directory,
        retention_count=setting.retention_count,
        updated_by_id=setting.updated_by_id,
        updated_at=setting.updated_at,
        supported=supported,
        support_message=reason,
    )


def run_to_read(run: BackupRun) -> BackupRunRead:
    return BackupRunRead(
        id=run.id,
        status=run.status,
        file_path=run.file_path,
        file_size_bytes=run.file_size_bytes,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.get("/settings", response_model=BackupSettingsRead)
def get_backup_settings(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BackupSettingsRead:
    setting = get_or_create_backup_settings(db)
    db.commit()
    db.refresh(setting)
    return settings_to_read(setting, db)


@router.patch("/settings", response_model=BackupSettingsRead)
def update_backup_settings(
    payload: BackupSettingsUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BackupSettingsRead:
    setting = get_or_create_backup_settings(db)
    if payload.enabled is not None:
        setting.enabled = payload.enabled
    if payload.frequency_minutes is not None:
        setting.frequency_minutes = payload.frequency_minutes
    if payload.target_directory is not None:
        target = payload.target_directory.strip()
        if not target:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Le dossier cible est obligatoire.")
        setting.target_directory = target
    if payload.retention_count is not None:
        setting.retention_count = payload.retention_count
    setting.updated_by_id = user.id
    db.commit()
    db.refresh(setting)
    return settings_to_read(setting, db)


@router.post("/run-now", response_model=BackupRunRead)
def run_backup_now(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BackupRunRead:
    run = run_backup(db, actor=user)
    db.commit()
    db.refresh(run)
    return run_to_read(run)


@router.get("/runs", response_model=BackupRunListResponse)
def list_backup_runs(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BackupRunListResponse:
    items = db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc(), BackupRun.id.desc())).all()
    return BackupRunListResponse(items=[run_to_read(item) for item in items], total=len(items))
