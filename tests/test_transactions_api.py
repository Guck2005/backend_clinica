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
from app.api.routes import auth, payments, transactions, visits
from app.core.security import hash_password
from app.db.base import Base
from app.integrations.fedapay import FedaPayInitiationResult, FedaPayStatusResult
from app.models.caisse import Caisse
from app.models.catalogue import CatalogueItem
from app.models.transaction import Transaction
from app.models.user import User
from app.models.visit import Visit


class FakeFedaPayProvider:
    def __init__(self) -> None:
        self.counter = 0
        self.status_by_attempt: dict[str, FedaPayStatusResult] = {}

    def start_mobile_money_payment(
        self,
        *,
        amount_fcfa: int,
        description: str,
        merchant_reference: str,
        operator_code: str,
        phone_number: str,
        metadata: dict,
    ) -> FedaPayInitiationResult:
        self.counter += 1
        attempt_id = f"fedapay-{self.counter}"
        result = FedaPayInitiationResult(
            provider_attempt_id=attempt_id,
            provider_status="pending",
            operator_code=operator_code,  # type: ignore[arg-type]
            phone_number=phone_number,
            raw_payload={
                "collection": {"id": attempt_id, "description": description, "merchant_reference": merchant_reference},
                "trigger": {"status": "pending", "amount": amount_fcfa},
                "metadata": metadata,
            },
        )
        self.status_by_attempt[attempt_id] = FedaPayStatusResult(
            provider_attempt_id=attempt_id,
            provider_status="pending",
            reference_paiement=None,
            raw_payload={"id": attempt_id, "status": "pending"},
        )
        return result

    def fetch_transaction_status(self, provider_attempt_id: str) -> FedaPayStatusResult:
        return self.status_by_attempt[provider_attempt_id]

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        return signature_header == "valid-signature" and bool(raw_body)

    def extract_webhook_transaction_id(self, payload: dict) -> str | None:
        if "transaction_id" in payload:
            return str(payload["transaction_id"])
        entity = payload.get("entity")
        if isinstance(entity, dict) and "id" in entity:
            return str(entity["id"])
        return None


@pytest.fixture()
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeFedaPayProvider:
    provider = FakeFedaPayProvider()
    monkeypatch.setattr(transactions, "get_fedapay_provider", lambda: provider)
    monkeypatch.setattr(payments, "get_fedapay_provider", lambda: provider)
    return provider


@pytest.fixture()
def client_and_session(tmp_path: Path):
    db_path = tmp_path / "transactions-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    with testing_session() as db:
        caisse_principale = Caisse(nom="Caisse principale", actif=True)
        autre_caisse = Caisse(nom="Caisse secondaire", actif=True)
        db.add_all([caisse_principale, autre_caisse])
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
                    nom="Autre Caissier",
                    identifiant="other.cashier",
                    role="caissier",
                    password_hash=hash_password("1234"),
                    actif=True,
                    caisse_id=autre_caisse.id,
                ),
                User(
                    nom="Jean Accueil",
                    identifiant="jean.a",
                    role="accueil",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Marie Dupont",
                    identifiant="marie.d",
                    role="superviseur",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Auditeur Demo",
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
                    code_element="CONS-GEN-01",
                    code_labo=None,
                    type="Consultation",
                    nom="Consultation generale",
                    service="Medecine generale",
                    montant_fcfa=2000,
                    hopital_id="HSJ-229",
                    actif=True,
                    metadata_json={},
                ),
                CatalogueItem(
                    code_element="ANAL-GLY-01",
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
                    code_element="MED-OFF-01",
                    code_labo=None,
                    type="Medicament",
                    nom="Produit inactif",
                    service="Pharmacie",
                    montant_fcfa=500,
                    hopital_id="HSJ-229",
                    actif=False,
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
                    motif_visite="Consultation",
                    service_oriente="Medecine generale",
                    agent_accueil_id=4,
                    statut="EN_CAISSE",
                ),
                Visit(
                    id_visite="VIS-0002",
                    patient_nom="Traore",
                    patient_prenom="Aicha",
                    patient_tel="+229 95 44 22 11",
                    patient_tel_normalized="22995442211",
                    motif_visite="Douleurs",
                    service_oriente="Medecine generale",
                    agent_accueil_id=4,
                    statut="EN_CAISSE",
                ),
                Visit(
                    id_visite="VIS-0003",
                    patient_nom="Mensah",
                    patient_prenom="Kofi",
                    patient_tel="+229 96 55 44 33",
                    patient_tel_normalized="22996554433",
                    motif_visite="Controle",
                    service_oriente="Cardiologie",
                    agent_accueil_id=4,
                    statut="SOLDE",
                ),
                Visit(
                    id_visite="VIS-0004",
                    patient_nom="Boco",
                    patient_prenom="Sena",
                    patient_tel="+229 71 00 11 22",
                    patient_tel_normalized="22971001122",
                    motif_visite="Controle",
                    service_oriente="Laboratoire",
                    agent_accueil_id=4,
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
    app.include_router(payments.router)
    app.include_router(transactions.router)
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


def create_cash_payload(id_visite: str = "VIS-0001") -> dict:
    return {
        "id_visite": id_visite,
        "lignes": [
            {"catalogue_item_id": 1, "quantite": 2, "payable": True},
            {"catalogue_item_id": 2, "quantite": 1, "payable": False, "motif_non_honore": "Indisponibilite financiere"},
        ],
        "paiement": {
            "moyen_paiement": "ESPECES",
            "montant_recu_fcfa": 4000,
        },
    }


def create_mobile_money_payload(id_visite: str = "VIS-0002", telephone_paiement: str | None = None) -> dict:
    paiement: dict[str, str] = {"moyen_paiement": "MOBILE_MONEY"}
    if telephone_paiement is not None:
        paiement["telephone_paiement"] = telephone_paiement
    return {
        "id_visite": id_visite,
        "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
        "paiement": paiement,
    }


def test_create_cash_transaction_allowed_for_cashier_and_admin(client_and_session) -> None:
    client, testing_session = client_and_session
    cashier_headers = auth_headers(client, "amadou.k")

    created = client.post("/transactions", headers=cashier_headers, json=create_cash_payload())
    assert created.status_code == 201
    body = created.json()
    assert body["id_visite"] == "VIS-0001"
    assert body["caisse_id"] == 1
    assert body["caissier_id"] == 2
    assert body["montant_total_fcfa"] == 5500
    assert body["montant_encaisse_fcfa"] == 4000
    assert body["statut"] == "PARTIELLEMENT_SOLDE"
    assert body["payment"]["moyen_paiement"] == "ESPECES"
    assert body["payment"]["statut"] == "CONFIRME"

    with testing_session() as db:
        visit = db.scalar(select(Visit).where(Visit.id_visite == "VIS-0001"))
        assert visit is not None
        assert visit.statut == "PARTIELLEMENT_SOLDE"

    admin_headers = auth_headers(client, "admin")
    admin_payload = {
        "id_visite": "VIS-0002",
        "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
        "paiement": {"moyen_paiement": "CHEQUE", "cheque_numero": "CHQ-009", "cheque_banque": "BOA", "cheque_titulaire": "Fatima Kouassi"},
    }
    admin_created = client.post("/transactions", headers=admin_headers, json=admin_payload)
    assert admin_created.status_code == 201
    admin_body = admin_created.json()
    assert admin_body["caisse_id"] is None
    assert admin_body["caissier_id"] == 1
    assert admin_body["payment"]["statut"] == "RECU"


def test_create_transaction_refused_for_non_cash_roles(client_and_session) -> None:
    client, _ = client_and_session
    payload = create_cash_payload()

    for identifiant in ["jean.a", "marie.d", "auditeur"]:
        response = client.post("/transactions", headers=auth_headers(client, identifiant), json=payload)
        assert response.status_code == 403


def test_mobile_money_creation_starts_pending_and_blocks_manual_reference(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    assert body["statut"] == "EN_ATTENTE"
    assert body["payment"]["statut"] == "EN_ATTENTE"
    assert body["payment"]["provider"] == "FEDAPAY"
    assert body["payment"]["provider_status"] == "pending"
    assert body["payment"]["operator_code"] == "MOOV"
    assert body["payment"]["reference_paiement"] is None
    assert body["payment"]["provider_attempt_id"] in fake_provider.status_by_attempt

    with testing_session() as db:
        visit = db.scalar(select(Visit).where(Visit.id_visite == "VIS-0002"))
        assert visit is not None
        assert visit.statut == "EN_CAISSE"

    manual_reference = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0004",
            "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "MOBILE_MONEY", "reference_paiement": "MANUAL-REF"},
        },
    )
    assert manual_reference.status_code == 422


def test_mobile_money_creation_accepts_payment_phone_override(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = client.post(
        "/transactions",
        headers=headers,
        json=create_mobile_money_payload("VIS-0004", "+229 97 00 11 22"),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["statut"] == "EN_ATTENTE"
    assert body["payment"]["statut"] == "EN_ATTENTE"
    assert body["payment"]["operator_code"] == "MTN"
    assert body["payment"]["telephone_paiement"] == "+229 97 00 11 22"
    assert body["payment"]["provider_attempt_id"] in fake_provider.status_by_attempt


def test_create_transaction_rejects_invalid_mobile_money_prefix(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    response = client.post("/transactions", headers=headers, json=create_mobile_money_payload("VIS-0004"))
    assert response.status_code == 422
    assert "operateur" in response.json()["detail"].lower()


def test_create_transaction_rejects_inactive_or_missing_items_and_duplicates(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    missing_item = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [{"catalogue_item_id": 999, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1000},
        },
    )
    assert missing_item.status_code == 422

    inactive_item = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [{"catalogue_item_id": 3, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 500},
        },
    )
    assert inactive_item.status_code == 422

    duplicate_items = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [
                {"catalogue_item_id": 1, "quantite": 1, "payable": True},
                {"catalogue_item_id": 1, "quantite": 2, "payable": True},
            ],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 6000},
        },
    )
    assert duplicate_items.status_code == 422


def test_create_transaction_rejects_invalid_line_rules(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    invalid_quantity = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [{"catalogue_item_id": 1, "quantite": 0, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1000},
        },
    )
    assert invalid_quantity.status_code == 422

    missing_reason = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": False}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1000},
        },
    )
    assert missing_reason.status_code == 422

    no_payable_lines = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [
                {"catalogue_item_id": 1, "quantite": 1, "payable": False, "motif_non_honore": "Indisponibilite"},
            ],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 1000},
        },
    )
    assert no_payable_lines.status_code == 422


def test_transaction_status_and_amounts_are_calculated_server_side(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    response = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0001",
            "lignes": [
                {"catalogue_item_id": 1, "quantite": 3, "payable": True},
                {"catalogue_item_id": 2, "quantite": 2, "payable": True},
            ],
            "paiement": {"moyen_paiement": "CHEQUE", "cheque_numero": "CHQ-009", "cheque_banque": "BOA", "cheque_titulaire": "Fatima Kouassi"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["statut"] == "SOLDE"
    assert body["montant_total_fcfa"] == 9000
    assert body["montant_encaisse_fcfa"] == 9000
    assert body["payment"]["statut"] == "RECU"


def test_cannot_create_second_transaction_for_same_visit(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    first = client.post("/transactions", headers=headers, json=create_cash_payload())
    assert first.status_code == 201

    second = client.post("/transactions", headers=headers, json=create_cash_payload())
    assert second.status_code == 409


def test_failed_transaction_can_be_reused_with_new_lines_and_payment_method(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")

    created = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    transaction_id = body["id"]
    attempt_id = body["payment"]["provider_attempt_id"]

    fake_provider.status_by_attempt[attempt_id] = FedaPayStatusResult(
        provider_attempt_id=attempt_id,
        provider_status="declined",
        reference_paiement=None,
        raw_payload={"id": attempt_id, "status": "declined", "last_error_code": "INSUFFICIENT_FUND_ERROR"},
    )
    refreshed = client.post(f"/transactions/{transaction_id}/refresh-provider-status", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["statut"] == "ECHOUE"

    resumed = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0002",
            "lignes": [
                {"catalogue_item_id": 1, "quantite": 2, "payable": True},
                {"catalogue_item_id": 2, "quantite": 1, "payable": False, "motif_non_honore": "Indisponibilite financiere"},
            ],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 4000},
        },
    )
    assert resumed.status_code == 201
    resumed_body = resumed.json()
    assert resumed_body["id"] == transaction_id
    assert resumed_body["statut"] == "PARTIELLEMENT_SOLDE"
    assert resumed_body["montant_total_fcfa"] == 5500
    assert resumed_body["montant_encaisse_fcfa"] == 4000
    assert resumed_body["payment"]["attempt_no"] == 2
    assert resumed_body["payment"]["moyen_paiement"] == "ESPECES"
    assert resumed_body["payment"]["statut"] == "CONFIRME"
    assert len(resumed_body["lines"]) == 2
    assert resumed_body["lines"][0]["quantite"] == 2

    with testing_session() as db:
        tx = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
        assert tx is not None
        assert len(tx.payments) == 2
        visit = db.scalar(select(Visit).where(Visit.id_visite == "VIS-0002"))
        assert visit is not None
        assert visit.statut == "PARTIELLEMENT_SOLDE"


def test_get_transaction_by_visit_returns_existing_transaction(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")
    create_response = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert create_response.status_code == 201

    fetched = client.get("/transactions/by-visit/VIS-0002", headers=headers)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id_visite"] == "VIS-0002"
    assert body["statut"] == "EN_ATTENTE"
    assert body["payment"]["provider_status"] == "pending"


def test_refresh_status_approved_finalizes_transaction(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")
    created = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    attempt_id = body["payment"]["provider_attempt_id"]
    transaction_id = body["id"]

    fake_provider.status_by_attempt[attempt_id] = FedaPayStatusResult(
        provider_attempt_id=attempt_id,
        provider_status="approved",
        reference_paiement="FEDA-REF-001",
        raw_payload={"id": attempt_id, "status": "approved", "reference": "FEDA-REF-001", "mode": "moov", "amount_debited": 2000, "fees": 20},
    )

    refreshed = client.post(f"/transactions/{transaction_id}/refresh-provider-status", headers=headers)
    assert refreshed.status_code == 200
    refreshed_body = refreshed.json()
    assert refreshed_body["statut"] == "SOLDE"
    assert refreshed_body["payment"]["statut"] == "CONFIRME"
    assert refreshed_body["payment"]["reference_paiement"] == "FEDA-REF-001"
    assert refreshed_body["payment"]["provider_error_code"] is None

    with testing_session() as db:
        visit = db.scalar(select(Visit).where(Visit.id_visite == "VIS-0002"))
        assert visit is not None
        assert visit.statut == "SOLDE"


def test_refresh_status_failed_keeps_visit_open_and_allows_retry(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")
    created = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    attempt_id = body["payment"]["provider_attempt_id"]
    transaction_id = body["id"]

    fake_provider.status_by_attempt[attempt_id] = FedaPayStatusResult(
        provider_attempt_id=attempt_id,
        provider_status="declined",
        reference_paiement=None,
        raw_payload={
            "id": attempt_id,
            "status": "declined",
            "last_error_code": "API_ERROR",
            "mode": "moov",
            "amount_debited": 1120,
            "fees": 20,
        },
    )

    refreshed = client.post(f"/transactions/{transaction_id}/refresh-provider-status", headers=headers)
    assert refreshed.status_code == 200
    refreshed_body = refreshed.json()
    assert refreshed_body["statut"] == "ECHOUE"
    assert refreshed_body["payment"]["statut"] == "ECHOUE"
    assert refreshed_body["payment"]["reference_paiement"] is None
    assert refreshed_body["payment"]["provider_error_code"] == "API_ERROR"
    assert refreshed_body["payment"]["provider_mode"] == "moov"
    assert refreshed_body["payment"]["provider_amount_debited_fcfa"] == 1120
    assert refreshed_body["payment"]["provider_fees_fcfa"] == 20

    with testing_session() as db:
        visit = db.scalar(select(Visit).where(Visit.id_visite == "VIS-0002"))
        assert visit is not None
        assert visit.statut == "EN_CAISSE"

    retried = client.post(f"/transactions/{transaction_id}/payments/mobile-money/retry", headers=headers)
    assert retried.status_code == 200
    retried_body = retried.json()
    assert retried_body["statut"] == "EN_ATTENTE"
    assert retried_body["payment"]["statut"] == "EN_ATTENTE"
    assert retried_body["payment"]["attempt_no"] == 2
    assert retried_body["payment"]["provider_attempt_id"] != attempt_id


def test_retry_mobile_money_accepts_new_payment_phone(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")
    created = client.post("/transactions", headers=headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    attempt_id = body["payment"]["provider_attempt_id"]
    transaction_id = body["id"]

    fake_provider.status_by_attempt[attempt_id] = FedaPayStatusResult(
        provider_attempt_id=attempt_id,
        provider_status="declined",
        reference_paiement=None,
        raw_payload={"id": attempt_id, "status": "declined", "last_error_code": "INSUFFICIENT_FUND_ERROR"},
    )
    refreshed = client.post(f"/transactions/{transaction_id}/refresh-provider-status", headers=headers)
    assert refreshed.status_code == 200

    retried = client.post(
        f"/transactions/{transaction_id}/payments/mobile-money/retry",
        headers=headers,
        json={"telephone_paiement": "+229 97 88 77 66"},
    )
    assert retried.status_code == 200
    retried_body = retried.json()
    assert retried_body["payment"]["attempt_no"] == 2
    assert retried_body["payment"]["operator_code"] == "MTN"
    assert retried_body["payment"]["telephone_paiement"] == "+229 97 88 77 66"
    assert retried_body["payment"]["provider_attempt_id"] != attempt_id


def test_webhook_confirm_and_cashier_scope(client_and_session, fake_provider: FakeFedaPayProvider) -> None:
    client, _ = client_and_session
    cashier_headers = auth_headers(client, "amadou.k")
    other_cashier_headers = auth_headers(client, "other.cashier")
    supervisor_headers = auth_headers(client, "marie.d")
    created = client.post("/transactions", headers=cashier_headers, json=create_mobile_money_payload())
    assert created.status_code == 201
    body = created.json()
    attempt_id = body["payment"]["provider_attempt_id"]
    transaction_id = body["id"]

    forbidden_read = client.get("/transactions/by-visit/VIS-0002", headers=other_cashier_headers)
    assert forbidden_read.status_code == 404

    supervisor_read = client.get("/transactions/by-visit/VIS-0002", headers=supervisor_headers)
    assert supervisor_read.status_code == 200

    forbidden_retry = client.post(f"/transactions/{transaction_id}/payments/mobile-money/retry", headers=other_cashier_headers)
    assert forbidden_retry.status_code == 404

    fake_provider.status_by_attempt[attempt_id] = FedaPayStatusResult(
        provider_attempt_id=attempt_id,
        provider_status="approved",
        reference_paiement="FEDA-WEBHOOK-002",
        raw_payload={"id": attempt_id, "status": "approved", "reference": "FEDA-WEBHOOK-002", "mode": "moov"},
    )
    webhook_response = client.post(
        "/payments/fedapay/webhook",
        content='{"transaction_id":"%s"}' % attempt_id,
        headers={"X-FEDAPAY-SIGNATURE": "valid-signature", "Content-Type": "application/json"},
    )
    assert webhook_response.status_code == 202

    fetched = client.get("/transactions/by-visit/VIS-0002", headers=cashier_headers)
    assert fetched.status_code == 200
    assert fetched.json()["payment"]["reference_paiement"] == "FEDA-WEBHOOK-002"
    assert fetched.json()["statut"] == "SOLDE"


def test_already_solved_visit_is_rejected(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "amadou.k")

    response = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0003",
            "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 2000},
        },
    )
    assert response.status_code == 409


def test_open_cashier_on_finalized_visit_is_idempotent(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "amadou.k")
    create_response = client.post(
        "/transactions",
        headers=headers,
        json={
            "id_visite": "VIS-0002",
            "lignes": [{"catalogue_item_id": 1, "quantite": 1, "payable": True}],
            "paiement": {"moyen_paiement": "ESPECES", "montant_recu_fcfa": 2000},
        },
    )
    assert create_response.status_code == 201

    reopened = client.post("/visits/VIS-0002/open-cashier", headers=headers)
    assert reopened.status_code == 200
    assert reopened.json()["statut"] == "SOLDE"

    with testing_session() as db:
        tx = db.scalar(select(Transaction).join(Visit).where(Visit.id_visite == "VIS-0002"))
        assert tx is not None
