from __future__ import annotations

import logging
from threading import Event, Thread
from time import sleep

from app.core.alerting import sweep_business_alerts
from app.core.backups import maybe_run_scheduled_backup
from app.core.config import settings
from app.core.sync_jobs import process_pending_sync_jobs
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)
_stop_event = Event()
_worker_thread: Thread | None = None


def _worker_loop() -> None:
    alert_counter = 0
    backup_counter = 0
    while not _stop_event.is_set():
        try:
            with SessionLocal() as db:
                process_pending_sync_jobs(db)
                alert_counter += settings.sync_worker_interval_seconds
                backup_counter += settings.sync_worker_interval_seconds
                if alert_counter >= settings.alert_sweep_interval_seconds:
                    sweep_business_alerts(db)
                    alert_counter = 0
                if backup_counter >= settings.backup_worker_interval_seconds:
                    maybe_run_scheduled_backup(db)
                    backup_counter = 0
                db.commit()
        except Exception as exc:  # pragma: no cover - defensive background loop
            logger.exception("Background worker error: %s", exc)
        _stop_event.wait(settings.sync_worker_interval_seconds)


def start_background_workers() -> None:
    global _worker_thread
    if not settings.background_workers_enabled:
        return
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = Thread(target=_worker_loop, name="caissetrace-background-worker", daemon=True)
    _worker_thread.start()


def stop_background_workers() -> None:
    _stop_event.set()
