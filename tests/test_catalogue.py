import pytest
from pathlib import Path

from app.scripts.catalogue_parser import split_entries, parse_entry


def test_catalogue_tex_contains_244_entries() -> None:
    source = Path(__file__).resolve().parents[2] / "catalogue.tex"
    if not source.exists():
        pytest.skip("catalogue.tex not found")
    entries = split_entries(source.read_text(encoding="utf-8"))
    assert len(entries) == 244


def test_parse_first_entry() -> None:
    source = Path(__file__).resolve().parents[2] / "catalogue.tex"
    if not source.exists():
        pytest.skip("catalogue.tex not found")
    number, raw = split_entries(source.read_text(encoding="utf-8"))[0]
    item = parse_entry(number, raw)
    assert item["code_element"] == "BIO-001"
    assert item["code_labo"] == "B70"
    assert item["montant_fcfa"] == 15400
    assert item["type"] == "Analyse"
    assert item["service"] == "Laboratoire"
