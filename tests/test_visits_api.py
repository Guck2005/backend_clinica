from datetime import datetime, timedelta
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.deps import get_db
from app.api.routes import auth, visits
from app.core.security import hash_password
from app.db.base import Base
from app.models.caisse import Caisse
from app.models.user import User
from app.models.visit import Visit


@pytest.fixture()
def client_and_session(tmp_path: Path):
    db_path = tmp_path / "visits-test.db"
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
                    nom="Jean Accueil",
                    identifiant="jean.a",
                    role="accueil",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Amadou Keita",
                    identifiant="amadou.k",
                    role="caissier",
                    password_hash=hash_password("1234"),
                    actif=True,
                    caisse_id=caisse.id,
                ),
                User(
                    nom="Aicha Accueil",
                    identifiant="aicha.a",
                    role="accueil",
                    password_hash=hash_password("1234"),
                    actif=True,
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
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_visit(client: TestClient, headers: dict[str, str], **overrides):
    payload = {
        "patient_nom": "Kouassi",
        "patient_prenom": "Fatima",
        "patient_tel": "97 12 34 56",
        "motif_visite": "Consultation generale",
        "service_oriente": "Medecine generale",
    }
    payload.update(overrides)
    return client.post("/visits", json=payload, headers=headers)


def test_create_visit_allowed_for_accueil_and_refused_for_caissier(client_and_session) -> None:
    client, _ = client_and_session
    accueil_headers = auth_headers(client, "jean.a")
    caissier_headers = auth_headers(client, "amadou.k")

    success = create_visit(client, accueil_headers)
    assert success.status_code == 201
    body = success.json()
    assert body["id_visite"] == "VIS-0001"
    assert body["patient_tel"] == "+229 97 12 34 56"
    assert body["statut"] == "EN_ATTENTE"

    forbidden = create_visit(client, caissier_headers, patient_nom="Traore")
    assert forbidden.status_code == 403


def test_visit_id_sequence_is_unique_and_stable(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "jean.a")

    first = create_visit(client, headers).json()
    second = create_visit(
        client,
        headers,
        patient_nom="Mensah",
        patient_prenom="Kofi",
        patient_tel="+229 96 55 44 33",
    ).json()

    assert first["id_visite"] == "VIS-0001"
    assert second["id_visite"] == "VIS-0002"


def test_search_by_id_name_prenom_and_phone(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "jean.a")
    created = create_visit(
        client,
        headers,
        patient_nom="Traore",
        patient_prenom="Aicha",
        patient_tel="95 44 22 11",
    ).json()

    common_headers = auth_headers(client, "admin")

    by_id = client.get("/visits", params={"search": created["id_visite"]}, headers=common_headers)
    assert by_id.status_code == 200
    assert by_id.json()["total"] == 1

    by_name = client.get("/visits", params={"search": "Traore"}, headers=common_headers)
    assert by_name.json()["total"] == 1

    by_prenom = client.get("/visits", params={"search": "Aicha"}, headers=common_headers)
    assert by_prenom.json()["total"] == 1

    by_phone = client.get("/visits", params={"search": "95442211"}, headers=common_headers)
    assert by_phone.json()["total"] == 1


def test_telephone_exact_matches_even_with_different_formatting(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "jean.a")
    create_visit(client, headers, patient_tel="97 12 34 56")

    admin_headers = auth_headers(client, "admin")
    response = client.get(
        "/visits",
        params={"telephone_exact": "+22997123456"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["patient_tel"] == "+229 97 12 34 56"


def test_today_only_filters_out_older_visits(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        yesterday = datetime.now() - timedelta(days=1)
        db.add_all(
            [
                Visit(
                    id_visite="VIS-0099",
                    patient_nom="Ancien",
                    patient_prenom="Patient",
                    patient_tel="+229 90 00 00 00",
                    patient_tel_normalized="22990000000",
                    motif_visite="Controle",
                    service_oriente="Cardiologie",
                    agent_accueil_id=2,
                    statut="EN_ATTENTE",
                    created_at=yesterday,
                    updated_at=yesterday,
                ),
                Visit(
                    id_visite="VIS-0100",
                    patient_nom="Nouveau",
                    patient_prenom="Patient",
                    patient_tel="+229 91 11 11 11",
                    patient_tel_normalized="22991111111",
                    motif_visite="Controle",
                    service_oriente="Cardiologie",
                    agent_accueil_id=2,
                    statut="EN_ATTENTE",
                ),
            ]
        )
        db.commit()

    response = client.get("/visits", params={"today_only": True}, headers=headers)
    assert response.status_code == 200
    ids = [item["id_visite"] for item in response.json()["items"]]
    assert "VIS-0100" in ids
    assert "VIS-0099" not in ids


def test_open_cashier_moves_status_and_is_idempotent(client_and_session) -> None:
    client, testing_session = client_and_session
    accueil_headers = auth_headers(client, "jean.a")
    caissier_headers = auth_headers(client, "amadou.k")
    visit = create_visit(client, accueil_headers).json()

    opened = client.post(f"/visits/{visit['id_visite']}/open-cashier", headers=caissier_headers)
    assert opened.status_code == 200
    assert opened.json()["statut"] == "EN_CAISSE"

    reopened = client.post(f"/visits/{visit['id_visite']}/open-cashier", headers=caissier_headers)
    assert reopened.status_code == 200
    assert reopened.json()["statut"] == "EN_CAISSE"

    with testing_session() as db:
        row = db.scalar(select(Visit).where(Visit.id_visite == visit["id_visite"]))
        assert row is not None
        row.statut = "SOLDE"
        db.commit()

    solved = client.post(f"/visits/{visit['id_visite']}/open-cashier", headers=caissier_headers)
    assert solved.status_code == 200
    assert solved.json()["statut"] == "SOLDE"


def test_accueil_scope_is_limited_outside_today_listing(client_and_session) -> None:
    client, _ = client_and_session
    jean_headers = auth_headers(client, "jean.a")
    aicha_headers = auth_headers(client, "aicha.a")
    admin_headers = auth_headers(client, "admin")

    jean_visit = create_visit(client, jean_headers, patient_nom="JeanPatient")
    assert jean_visit.status_code == 201
    aicha_visit = create_visit(client, aicha_headers, patient_nom="AichaPatient")
    assert aicha_visit.status_code == 201

    own_only = client.get("/visits", headers=jean_headers)
    assert own_only.status_code == 200
    own_ids = [item["id_visite"] for item in own_only.json()["items"]]
    assert jean_visit.json()["id_visite"] in own_ids
    assert aicha_visit.json()["id_visite"] not in own_ids

    today_listing = client.get("/visits", params={"today_only": True}, headers=jean_headers)
    assert today_listing.status_code == 200
    today_ids = [item["id_visite"] for item in today_listing.json()["items"]]
    assert jean_visit.json()["id_visite"] in today_ids
    assert aicha_visit.json()["id_visite"] in today_ids

    admin_listing = client.get("/visits", headers=admin_headers)
    assert admin_listing.status_code == 200
    assert admin_listing.json()["total"] == 2
