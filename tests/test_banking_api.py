from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_db
from app.api.routes import alerts, auth, factures, payments, transactions, versements, visits
from app.integrations.brevo_sms import SmsSendResult
from app.core.security import hash_password
from app.db.base import Base
from app.models.alert import Alert
from app.models.caisse import Caisse
from app.models.catalogue import CatalogueItem
from app.models.invoice import Invoice
from app.models.transaction import Payment
from app.models.user import User
from app.models.versement import Versement
from app.models.visit import Visit


@pytest.fixture()
def client_and_session(tmp_path: Path):
    db_path = tmp_path / "banking-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    with testing_session() as db:
        caisse_principale = Caisse(nom="Caisse principale", actif=True)
        caisse_secondaire = Caisse(nom="Caisse secondaire", actif=True)
        db.add_all([caisse_principale, caisse_secondaire])
        db.flush()
        db.add_all(
            [
                User(
                    nom="Administrateur",
                    identifiant="admin",
                    role="admin",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Amadou Keita",
                    identifiant="amadou.k",
                    role="caissier",
                    password_hash=hash_password("1234"),
                    actif=True,
                    caisse_id=caisse_principale.id,
                ),
                User(
                    nom="Superviseur",
                    identifiant="marie.d",
                    role="superviseur",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Auditeur",
                    identifiant="auditeur",
                    role="auditeur",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
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
                ),
                CatalogueItem(
                    code_element="BIO-002",
                    code_labo="B71",
                    type="Analyse",
                    nom="Acetone urines",
                    service="Laboratoire",
                    montant_fcfa=1100,
                    hopital_id="HSJ-229",
                    actif=True,
                    metadata_json={},
                ),
            ]
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
                    agent_accueil_id=1,
                    statut="EN_CAISSE",
                ),
                Visit(
                    id_visite="VIS-0002",
                    patient_nom="Traore",
                    patient_prenom="Aicha",
                    patient_tel="+229 95 44 22 11",
                    patient_tel_normalized="22995442211",
                    motif_visite="Controle",
                    service_oriente="Laboratoire",
                    agent_accueil_id=1,
                    statut="EN_CAISSE",
                ),
                Visit(
                    id_visite="VIS-0003",
                    patient_nom="Mensah",
                    patient_prenom="Kofi",
                    patient_tel="+229 96 55 44 33",
                    patient_tel_normalized="22996554433",
                    motif_visite="Analyse",
                    service_oriente="Laboratoire",
                    agent_accueil_id=1,
                    statut="EN_CAISSE",
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
    app.include_router(factures.router)
    app.include_router(payments.router)
    app.include_router(transactions.router)
    app.include_router(versements.router)
    app.include_router(visits.router)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, testing_session

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def auth_headers(client: TestClient, identifiant: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"identifiant": identifiant, "mot_de_passe": "1234"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_cheque_transaction(client: TestClient, headers: dict[str, str], id_visite: str = "VIS-0001"):
    return client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": id_visite,
            "lignes": [{"catalogue_item_id": 1, "quantite": 2, "payable": True}],
            "paiement": {
                "moyen_paiement": "CHEQUE",
                "cheque_numero": "CHQ-001",
                "cheque_banque": "BOA",
                "cheque_titulaire": "Fatima Kouassi",
            },
        },
    )


def create_cash_transaction(client: TestClient, headers: dict[str, str], id_visite: str = "VIS-0002"):
    return client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": id_visite,
            "lignes": [{"catalogue_item_id": 2, "quantite": 2, "payable": True}],
            "paiement": {
                "moyen_paiement": "ESPECES",
                "montant_recu_fcfa": 3000,
            },
        },
    )


def test_cheque_creation_creates_pending_invoice(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = create_cheque_transaction(client, headers)
    assert created.status_code == 201
    body = created.json()
    assert body["payment"]["statut"] == "RECU"
    assert body["statut"] == "SOLDE"
    assert body["can_reopen_in_cashier"] is False
    assert "confirmation bancaire" in body["blocking_reason"].lower()

    listed = client.get("/factures", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["statut_document"] == "EN_ATTENTE_CONFIRMATION_BANCAIRE"
    assert listed.json()["items"][0]["sms_status"] == "LOCAL_LOG"
    assert listed.json()["items"][0]["public_download_url"].endswith(".pdf")

    with testing_session() as db:
        invoice = db.scalar(select(Invoice))
        assert invoice is not None
        assert invoice.public_token
        assert invoice.mention_paiement is not None
        assert "en attente" in invoice.mention_paiement.lower()


def test_cheque_status_transitions_and_rejection_alert(client_and_session) -> None:
    client, testing_session = client_and_session
    cashier_headers = auth_headers(client, "amadou.k")
    supervisor_headers = auth_headers(client, "marie.d")

    created = create_cheque_transaction(client, cashier_headers)
    assert created.status_code == 201
    payment_id = created.json()["payment"]["id"]

    encashed = client.patch(
        f"/payments/cheques/{payment_id}/status",
        headers=supervisor_headers,
        json={"statut": "ENCAISSE"},
    )
    assert encashed.status_code == 200
    assert encashed.json()["statut"] == "ENCAISSE"

    facture = client.get("/factures", headers=supervisor_headers)
    assert facture.status_code == 200
    assert facture.json()["items"][0]["statut_document"] == "EMISE"

    created_second = create_cheque_transaction(client, cashier_headers, "VIS-0003")
    assert created_second.status_code == 201
    second_payment_id = created_second.json()["payment"]["id"]
    rejected = client.patch(
        f"/payments/cheques/{second_payment_id}/status",
        headers=supervisor_headers,
        json={"statut": "REJETE"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["statut"] == "REJETE"

    blocked = client.post(
        "/transactions",
        headers=cashier_headers,
        json={
            "id_visite": "VIS-0003",
            "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1500},
        },
    )
    assert blocked.status_code == 409
    assert "bloque" in blocked.json()["detail"].lower()

    alerts_list = client.get("/alerts", headers=supervisor_headers, params={"rule_code": "A5"})
    assert alerts_list.status_code == 200
    assert alerts_list.json()["total"] == 1

    with testing_session() as db:
        alert = db.scalar(select(Alert).where(Alert.rule_code == "CHEQUE_REJETE_APRES_FACTURE"))
        assert alert is not None
        assert alert.source_type == "CHEQUE_PAYMENT"


def test_cash_transaction_persists_received_amount_and_invoice(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")

    invalid = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0002",
            "lignes": [{"catalogue_item_id": 2, "quantite": 2, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1000},
        },
    )
    assert invalid.status_code == 422

    created = create_cash_transaction(client, headers)
    assert created.status_code == 201
    body = created.json()
    assert body["payment"]["statut"] == "CONFIRME"
    assert body["payment"]["montant_recu_fcfa"] == 3000
    assert body["payment"]["monnaie_rendue_fcfa"] == 800

    listed = client.get("/transactions", headers=headers, params={"payment_method": "ESPECES"})
    assert listed.status_code == 200
    assert listed.json()["summary"]["especes_fcfa"] == 2200

    with testing_session() as db:
        payment = db.scalar(select(Payment).where(Payment.moyen_paiement == "ESPECES"))
        assert payment is not None
        assert payment.raw_payload == {"montant_recu_fcfa": 3000, "monnaie_rendue_fcfa": 800}
        invoice = db.scalar(select(Invoice).where(Invoice.transaction_id == payment.transaction_id))
        assert invoice is not None
        assert invoice.statut_document == "EMISE"
        assert invoice.sms_status == "LOCAL_LOG"


def test_invoice_pdf_routes_and_public_token(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = create_cash_transaction(client, headers)
    assert created.status_code == 201

    listed = client.get("/factures", headers=headers)
    assert listed.status_code == 200
    invoice = listed.json()["items"][0]
    token = invoice["public_download_url"].rsplit("/", 1)[-1].removesuffix(".pdf")

    protected_pdf = client.get(f"/factures/{invoice['numero_facture']}/pdf", headers=headers)
    assert protected_pdf.status_code == 200
    assert protected_pdf.headers["content-type"].startswith("application/pdf")
    assert protected_pdf.content.startswith(b"%PDF")
    assert b"FA-229-" in protected_pdf.content

    public_pdf = client.get(f"/public/factures/{token}.pdf")
    assert public_pdf.status_code == 200
    assert public_pdf.content.startswith(b"%PDF")

    missing_pdf = client.get("/public/factures/invalide.pdf")
    assert missing_pdf.status_code == 404


def test_invoice_pdf_mentions_non_honored_lines(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0002",
            "lignes": [
                {"catalogue_item_id": 1, "quantite": 1, "payable": True},
                {"catalogue_item_id": 2, "quantite": 1, "payable": False, "motif_non_honore": "Patient sans ordonnance"},
            ],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1500},
        },
    )
    assert created.status_code == 201
    invoice_number = created.json()["invoice_number"]

    pdf = client.get(f"/factures/{invoice_number}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert b"Non honore" in pdf.content
    assert b"reglement" in pdf.content


def test_invoice_manual_sms_resend_uses_provider_when_mocked(client_and_session, monkeypatch) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = create_cash_transaction(client, headers)
    assert created.status_code == 201
    invoice_number = client.get("/factures", headers=headers).json()["items"][0]["numero_facture"]

    class StubSmsProvider:
        def send_sms(self, *, recipient: str, content: str) -> SmsSendResult:
            assert recipient == "22995442211"
            assert invoice_number in content
            return SmsSendResult(status="ENVOYE", provider="BREVO", message_id="brevo-123")

    monkeypatch.setattr("app.core.finance.get_sms_provider", lambda: StubSmsProvider())

    resent = client.post(f"/factures/{invoice_number}/send-sms", headers=headers)
    assert resent.status_code == 200
    assert resent.json()["sms_status"] == "ENVOYE"
    assert resent.json()["sms_sent_at"] is not None


def test_transactions_filters_and_summaries(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")
    create_cheque_transaction(client, headers, "VIS-0001")
    create_cash_transaction(client, headers, "VIS-0002")

    listed = client.get(
        "/transactions",
        headers=headers,
        params={"search": "Fatima", "payment_status": "RECU"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["payment"]["moyen_paiement"] == "CHEQUE"
    assert listed.json()["summary"]["cheques_fcfa"] == 3000


def test_versements_theoretical_create_alert_and_download_receipt(client_and_session) -> None:
    client, testing_session = client_and_session
    cashier_headers = auth_headers(client, "amadou.k")
    supervisor_headers = auth_headers(client, "marie.d")
    create_cheque_transaction(client, cashier_headers, "VIS-0001")
    create_cash_transaction(client, cashier_headers, "VIS-0002")

    theoretical = client.get(
        "/versements/theoretical",
        headers=supervisor_headers,
        params={"caisse_ids": "1"},
    )
    assert theoretical.status_code == 200
    assert theoretical.json()["montant_theorique_fcfa"] == 5200

    created = client.post(
        "/versements",
        headers=supervisor_headers,
        data={
            "date_versement": datetime.now(timezone.utc).date().isoformat(),
            "scope": "UNIQUE",
            "caisse_ids": "1",
            "montant_compte_especes_fcfa": "5000",
            "montant_remis_cheques_fcfa": "0",
            "note": "Depot du soir",
        },
        files={"justificatif": ("bordereau.txt", b"preuve versement", "text/plain")},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["ecart_fcfa"] == -200
    assert body["versement_id"].startswith("VRS-")

    alerts_list = client.get("/alerts", headers=supervisor_headers, params={"rule_code": "A7"})
    assert alerts_list.status_code == 200
    assert alerts_list.json()["total"] == 1
    assert alerts_list.json()["items"][0]["rule_code"] == "ECART_VERSEMENT_BANCAIRE"

    history = client.get("/versements", headers=supervisor_headers)
    assert history.status_code == 200
    assert history.json()["total"] == 1

    download = client.get(f"/versements/{body['versement_id']}/justificatif", headers=supervisor_headers)
    assert download.status_code == 200
    assert download.content == b"preuve versement"
    assert download.headers["content-type"].startswith("text/plain")

    with testing_session() as db:
        versement = db.scalar(select(Versement))
        assert versement is not None
        assert versement.justificatif_filename == "bordereau.txt"
        assert versement.justificatif_bytes == b"preuve versement"


def test_old_transactions_can_be_filtered_by_date(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")
    create_cash_transaction(client, headers)

    with testing_session() as db:
        payment = db.scalar(select(Payment).where(Payment.moyen_paiement == "ESPECES"))
        assert payment is not None
        payment.created_at = datetime.now(timezone.utc) - timedelta(days=3)
        db.commit()

    today = datetime.now(timezone.utc).date().isoformat()
    listed = client.get("/transactions", headers=headers, params={"date_from": today, "date_to": today})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
