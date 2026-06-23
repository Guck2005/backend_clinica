from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.caisse import Caisse
from app.models.user import User


DEMO_CAISSES = [
    {"nom": "Caisse principale"},
]

DEMO_USERS = [
    {"nom": "Administrateur", "identifiant": "admin", "role": "admin"},
    {"nom": "Amadou Keita", "identifiant": "amadou.k", "role": "caissier"},
    {"nom": "Marie Dupont", "identifiant": "marie.d", "role": "superviseur"},
    {"nom": "Jean Accueil", "identifiant": "jean.a", "role": "accueil"},
    {"nom": "Auditeur Demo", "identifiant": "auditeur", "role": "auditeur"},
]


def ensure_demo_users() -> None:
    with SessionLocal() as db:
        default_caisse = None
        for demo_caisse in DEMO_CAISSES:
            caisse = db.scalar(select(Caisse).where(Caisse.nom == demo_caisse["nom"]))
            if caisse is None:
                caisse = Caisse(nom=demo_caisse["nom"], actif=True)
                db.add(caisse)
                db.flush()
            if demo_caisse["nom"] == "Caisse principale":
                default_caisse = caisse

        for demo in DEMO_USERS:
            existing = db.scalar(select(User).where(User.identifiant == demo["identifiant"]))
            if existing is None:
                db.add(
                    User(
                        nom=demo["nom"],
                        identifiant=demo["identifiant"],
                        role=demo["role"],
                        password_hash=hash_password("1234"),
                        actif=True,
                        caisse_id=default_caisse.id if demo["role"] == "caissier" and default_caisse else None,
                    )
                )
                continue
            if demo["role"] == "caissier" and default_caisse is not None and existing.caisse_id != default_caisse.id:
                existing.caisse_id = default_caisse.id
            if demo["role"] != "caissier" and existing.caisse_id is not None:
                existing.caisse_id = None
        db.commit()


if __name__ == "__main__":
    ensure_demo_users()
    print("Demo users ready")
