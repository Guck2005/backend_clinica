import sys
from pathlib import Path

from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.catalogue import CatalogueItem
from app.scripts.seed_demo_users import ensure_demo_users
from app.scripts.catalogue_parser import parse_entry, split_entries


def import_catalogue(path: Path) -> tuple[int, int]:
    Base.metadata.create_all(bind=engine)
    ensure_demo_users()

    text = path.read_text(encoding="utf-8")
    parsed = [parse_entry(number, raw) for number, raw in split_entries(text)]

    created = 0
    updated = 0
    with SessionLocal() as db:
        for payload in parsed:
            existing = db.scalar(
                select(CatalogueItem).where(CatalogueItem.code_element == payload["code_element"])
            )
            if existing is None:
                db.add(CatalogueItem(**payload))
                created += 1
                continue

            for key, value in payload.items():
                setattr(existing, key, value)
            updated += 1
        db.commit()

    return created, updated


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.scripts.import_catalogue_tex ../catalogue.tex")

    path = Path(sys.argv[1]).resolve()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    total_entries = len(split_entries(path.read_text(encoding="utf-8")))
    created, updated = import_catalogue(path)
    print(f"Catalogue entries found: {total_entries}")
    print(f"Created: {created}")
    print(f"Updated: {updated}")


if __name__ == "__main__":
    main()
