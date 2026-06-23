from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_db
from app.api.routes import alerts, audit_logs, auth, backups, reports, transactions
from app.core.security import hash_password
from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.backup import BackupRun
from app.models.caisse import Caisse
from app.models.catalogue import CatalogueItem
from app.models.user import User
from app.models.visit import Visit


def auth_headers(client: TestClient, identifiant: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"identifiant": identifiant, "mot_de_passe": "1234"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_reports_alerts_audit_and_backups(tmp_path: Path) -> None:
    db_path = tmp_path / "reports-audit-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    with testing_session() as db:
        caisse = Caisse(nom="Caisse principale", actif=True)
        db.add(caisse)
        db.flush()
        admin = User(nom="Admin", identifiant="admin", role="admin", password_hash=hash_password("1234"), actif=True)
        supervisor = User(nom="Supervisor", identifiant="marie.d", role="superviseur", password_hash=hash_password("1234"), actif=True)
        cashier = User(
            nom="Cashier",
            identifiant="amadou.k",
            role="caissier",
            password_hash=hash_password("1234"),
            actif=True,
            caisse_id=caisse.id,
        )
        db.add_all([admin, supervisor, cashier])
        db.flush()
        db.add(
            CatalogueItem(
                code_element="BIO-001",
                code_labo="B70",
                type="Analyse",
                nom="Glycemie a jeun",
                service="Laboratoire",
                montant_fcfa=1500,
                hopital_id="HSJ-229",
                actif=True,
                metadata_json={},
            )
        )
        db.flush()
        db.add_all(
            [
                Visit(
                    id_visite="VIS-0001",
                    patient_nom="Kouassi",
                    patient_prenom="Fatima",
                    patient_tel="+229 97 12 34 56",
                    patient_tel_normalized="22997123456",
                    motif_visite="Analyse",
                    service_oriente="Laboratoire",
                    agent_accueil_id=admin.id,
                    statut="EN_CAISSE",
                ),
                Visit(
                    id_visite="VIS-0002",
                    patient_nom="Traore",
                    patient_prenom="Aicha",
                    patient_tel="+229 95 44 22 11",
                    patient_tel_normalized="22995442211",
                    motif_visite="Consultation",
                    service_oriente="Medecine generale",
                    agent_accueil_id=admin.id,
                    statut="EN_ATTENTE",
                    created_at=datetime.now(timezone.utc) - timedelta(hours=5),
                ),
            ]
        )
        db.commit()

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(alerts.router)
    app.include_router(audit_logs.router)
    app.include_router(backups.router)
    app.include_router(reports.router)
    app.include_router(transactions.router)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        cashier_headers = auth_headers(client, "amadou.k")
        supervisor_headers = auth_headers(client, "marie.d")
        admin_headers = auth_headers(client, "admin")

        created = client.post(
            "/transactions",
            headers=cashier_headers,
            json={
                "id_visite": "VIS-0001",
                "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
                "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 2000},
            },
        )
        assert created.status_code == 201

        alerts_response = client.get("/alerts", headers=supervisor_headers, params={"status": "ACTIVE"})
        assert alerts_response.status_code == 200
        assert any(item["rule_name"] == "Dossier sans passage caisse apres quatre heures" for item in alerts_response.json()["items"])
        assert all(not item["rule_code"].startswith("A") for item in alerts_response.json()["items"])

        summary = client.get("/reports/summary", headers=supervisor_headers, params={"period": "day", "consolidated": True})
        assert summary.status_code == 200
        assert summary.json()["totals"]["encaisse_fcfa"] == 1500
        assert "conclusion" in summary.json()

        export = client.get(
            "/reports/export",
            headers=supervisor_headers,
            params={"report_type": "summary", "format": "csv", "period": "day", "consolidated": True},
        )
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("text/csv")

        audit_list = client.get("/audit-logs", headers=supervisor_headers)
        assert audit_list.status_code == 200
        assert audit_list.json()["total"] >= 2

        backup_settings = client.get("/admin/backups/settings", headers=admin_headers)
        assert backup_settings.status_code == 200
        assert backup_settings.json()["supported"] is True

        updated_settings = client.patch(
            "/admin/backups/settings",
            headers=admin_headers,
            json={"enabled": True, "frequency_minutes": 60, "retention_count": 5},
        )
        assert updated_settings.status_code == 200
        assert updated_settings.json()["enabled"] is True

        backup_run = client.post("/admin/backups/run-now", headers=admin_headers)
        assert backup_run.status_code == 200
        assert backup_run.json()["status"] == "SUCCEEDED"

    with testing_session() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action_code == "AUTH_LOGIN")) is not None
        assert db.scalar(select(BackupRun)) is not None

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
