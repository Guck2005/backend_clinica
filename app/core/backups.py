from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import shutil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.models.backup import BackupRun, BackupSetting
from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def current_database_url(db: Session) -> str:
    bind = db.get_bind()
    return str(bind.url) if bind is not None else ""


def backup_supported(db: Session) -> tuple[bool, str | None]:
    database_url = current_database_url(db)
    if not database_url.startswith("sqlite:///"):
        return False, "Les sauvegardes automatiques applicatives sont disponibles uniquement en mode SQLite local."
    db_path = database_url.removeprefix("sqlite:///")
    if db_path == ":memory:":
        return False, "La base SQLite en memoire ne peut pas etre sauvegardee sur disque."
    return True, None


def get_or_create_backup_settings(db: Session) -> BackupSetting:
    setting = db.scalar(select(BackupSetting).order_by(BackupSetting.id.asc()))
    if setting is None:
        setting = BackupSetting()
        db.add(setting)
        db.flush()
    return setting


def run_backup(
    db: Session,
    *,
    actor: User | None = None,
) -> BackupRun:
    setting = get_or_create_backup_settings(db)
    supported, reason = backup_supported(db)

    run = BackupRun(status="RUNNING")
    db.add(run)
    db.flush()

    if not supported:
        run.status = "FAILED"
        run.error_message = reason
        run.finished_at = utcnow()
        db.flush()
        log_audit(
            db,
            action_code="BACKUP_FAILED",
            action_label="Sauvegarde locale indisponible",
            entity_type="BACKUP_RUN",
            entity_id=str(run.id),
            actor=actor,
            detail={"reason": reason},
        )
        return run

    source_path = Path(current_database_url(db).removeprefix("sqlite:///")).resolve()
    target_directory = Path(setting.target_directory).expanduser()
    if not target_directory.is_absolute():
        target_directory = (Path.cwd() / target_directory).resolve()
    target_directory.mkdir(parents=True, exist_ok=True)

    timestamp = utcnow().strftime("%Y%m%d-%H%M%S")
    file_path = target_directory / f"caissetrace-backup-{timestamp}.sqlite3"

    try:
        shutil.copy2(source_path, file_path)
    except OSError as exc:
        run.status = "FAILED"
        run.error_message = str(exc)[:255]
        run.finished_at = utcnow()
        db.flush()
        log_audit(
            db,
            action_code="BACKUP_FAILED",
            action_label="Sauvegarde locale echouee",
            entity_type="BACKUP_RUN",
            entity_id=str(run.id),
            actor=actor,
            detail={"error": str(exc)},
        )
        return run

    run.status = "SUCCEEDED"
    run.file_path = str(file_path)
    run.file_size_bytes = file_path.stat().st_size if file_path.exists() else None
    run.finished_at = utcnow()
    db.flush()

    files = sorted(target_directory.glob("caissetrace-backup-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale_file in files[setting.retention_count :]:
        try:
            stale_file.unlink(missing_ok=True)
        except OSError:
            continue

    log_audit(
        db,
        action_code="BACKUP_CREATED",
        action_label="Sauvegarde locale creee",
        entity_type="BACKUP_RUN",
        entity_id=str(run.id),
        actor=actor,
        detail={"file_path": run.file_path, "file_size_bytes": run.file_size_bytes},
    )
    return run


def maybe_run_scheduled_backup(db: Session) -> BackupRun | None:
    setting = get_or_create_backup_settings(db)
    if not setting.enabled:
        return None

    latest = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc(), BackupRun.id.desc()))
    if latest and latest.started_at >= utcnow() - timedelta(minutes=setting.frequency_minutes):
        return None

    return run_backup(db, actor=None)
