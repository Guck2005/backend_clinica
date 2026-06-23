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
from app.api.routes import auth, caisses, users
from app.core.security import hash_password
from app.db.base import Base
from app.models.caisse import Caisse
from app.models.user import User


@pytest.fixture()
def client_and_session(tmp_path: Path):
    db_path = tmp_path / "accounts-test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    with testing_session() as db:
        caisse_principale = Caisse(nom="Caisse principale", actif=True)
        caisse_archivee = Caisse(nom="Caisse archivee", actif=False)
        db.add_all([caisse_principale, caisse_archivee])
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
                    nom="Marie Dupont",
                    identifiant="marie.d",
                    role="superviseur",
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
                    nom="Auditeur Demo",
                    identifiant="auditeur",
                    role="auditeur",
                    password_hash=hash_password("1234"),
                    actif=True,
                ),
                User(
                    nom="Compte Inactif",
                    identifiant="inactive",
                    role="admin",
                    password_hash=hash_password("1234"),
                    actif=False,
                ),
                User(
                    nom="Caissier Sans Caisse Active",
                    identifiant="bad.cashier",
                    role="caissier",
                    password_hash=hash_password("1234"),
                    actif=True,
                    caisse_id=caisse_archivee.id,
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
    app.include_router(caisses.router)
    app.include_router(users.router)
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, testing_session

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def login_response(client: TestClient, identifiant: str, mot_de_passe: str = "1234"):
    return client.post(
        "/auth/login",
        json={"identifiant": identifiant, "mot_de_passe": mot_de_passe},
    )


def auth_headers(client: TestClient, identifiant: str) -> dict[str, str]:
    response = login_response(client, identifiant)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_supports_roles_and_returns_caisse_metadata(client_and_session) -> None:
    client, _ = client_and_session

    for identifiant in ["admin", "amadou.k", "marie.d", "jean.a", "auditeur"]:
        response = login_response(client, identifiant)
        assert response.status_code == 200

    cashier_user = login_response(client, "amadou.k").json()["user"]
    assert cashier_user["caisse_id"] is not None
    assert cashier_user["caisse_nom"] == "Caisse principale"

    admin_user = login_response(client, "admin").json()["user"]
    assert admin_user["caisse_id"] is None
    assert admin_user["caisse_nom"] is None


def test_login_refuses_inactive_user_and_cashier_without_active_caisse(client_and_session) -> None:
    client, _ = client_and_session

    inactive = login_response(client, "inactive")
    assert inactive.status_code == 403
    assert inactive.json()["detail"] == "Ce compte est desactive."

    no_active_caisse = login_response(client, "bad.cashier")
    assert no_active_caisse.status_code == 403
    assert no_active_caisse.json()["detail"] == "Ce caissier n'a pas de caisse active affectee."


def test_create_cashier_requires_active_caisse(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        caisse_principale = db.scalar(select(Caisse).where(Caisse.nom == "Caisse principale"))
        caisse_archivee = db.scalar(select(Caisse).where(Caisse.nom == "Caisse archivee"))
        assert caisse_principale is not None
        assert caisse_archivee is not None
        active_id = caisse_principale.id
        inactive_id = caisse_archivee.id

    missing_caisse = client.post(
        "/users",
        headers=headers,
        json={
            "nom": "Nouveau Caissier",
            "identifiant": "new.cashier",
            "mot_de_passe": "1234",
            "role": "caissier",
        },
    )
    assert missing_caisse.status_code == 422

    inactive_caisse = client.post(
        "/users",
        headers=headers,
        json={
            "nom": "Nouveau Caissier",
            "identifiant": "new.cashier",
            "mot_de_passe": "1234",
            "role": "caissier",
            "caisse_id": inactive_id,
        },
    )
    assert inactive_caisse.status_code == 422

    created = client.post(
        "/users",
        headers=headers,
        json={
            "nom": "Nouveau Caissier",
            "identifiant": "new.cashier",
            "mot_de_passe": "1234",
            "role": "caissier",
            "caisse_id": active_id,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["role"] == "caissier"
    assert body["caisse_id"] == active_id
    assert body["caisse_nom"] == "Caisse principale"


def test_non_cashier_creation_forces_null_caisse(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        caisse_principale = db.scalar(select(Caisse).where(Caisse.nom == "Caisse principale"))
        assert caisse_principale is not None
        caisse_id = caisse_principale.id

    response = client.post(
        "/users",
        headers=headers,
        json={
            "nom": "Superviseur Bis",
            "identifiant": "super.bis",
            "mot_de_passe": "1234",
            "role": "superviseur",
            "caisse_id": caisse_id,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["caisse_id"] is None
    assert body["caisse_nom"] is None


def test_create_and_deactivate_caisse(client_and_session) -> None:
    client, _ = client_and_session
    headers = auth_headers(client, "admin")

    created = client.post("/caisses", headers=headers, json={"nom": "Caisse 3"})
    assert created.status_code == 201
    caisse_id = created.json()["id"]

    deactivated = client.patch(f"/caisses/{caisse_id}/deactivate", headers=headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["actif"] is False


def test_cannot_deactivate_caisse_with_active_cashier(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        caisse_principale = db.scalar(select(Caisse).where(Caisse.nom == "Caisse principale"))
        assert caisse_principale is not None
        caisse_id = caisse_principale.id

    response = client.patch(f"/caisses/{caisse_id}/deactivate", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Cette caisse a encore des caissiers actifs affectes."


def test_list_users_filters_by_role_actif_caisse_and_search(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        caisse_principale = db.scalar(select(Caisse).where(Caisse.nom == "Caisse principale"))
        assert caisse_principale is not None
        caisse_id = caisse_principale.id

    by_role = client.get("/users", headers=headers, params={"role": "caissier"})
    assert by_role.status_code == 200
    assert by_role.json()["total"] == 2

    by_actif = client.get("/users", headers=headers, params={"actif": False})
    assert by_actif.status_code == 200
    assert by_actif.json()["total"] == 1

    by_caisse = client.get("/users", headers=headers, params={"caisse_id": caisse_id})
    assert by_caisse.status_code == 200
    assert by_caisse.json()["total"] == 1
    assert by_caisse.json()["items"][0]["identifiant"] == "amadou.k"

    by_search = client.get("/users", headers=headers, params={"search": "Amadou"})
    assert by_search.status_code == 200
    assert by_search.json()["total"] == 1


def test_update_user_strips_caisse_when_role_changes(client_and_session) -> None:
    client, testing_session = client_and_session
    headers = auth_headers(client, "admin")

    with testing_session() as db:
        amadou = db.scalar(select(User).where(User.identifiant == "amadou.k"))
        assert amadou is not None
        user_id = amadou.id

    response = client.patch(
        f"/users/{user_id}",
        headers=headers,
        json={"role": "superviseur"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "superviseur"
    assert body["caisse_id"] is None
    assert body["caisse_nom"] is None
