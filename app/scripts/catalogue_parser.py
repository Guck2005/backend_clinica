import re


ENTRY_RE = re.compile(r"^\s*(\d+)\.\s+(.*)")
CODE_RE = re.compile(r"\bB\d+\b")
PRICE_RE = re.compile(r"\b(?:\d{1,3}(?:\s+\d{3})+|\d{3,})\b")


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_price(text: str) -> int | None:
    match = PRICE_RE.search(text)
    if match is None:
        return None
    return int(match.group(0).replace(" ", ""))


def split_entries(text: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None

    for line in text.splitlines():
        match = ENTRY_RE.match(line)
        if match:
            if current is not None:
                entries.append(current)
            current = (int(match.group(1)), [match.group(2)])
            continue
        if current is not None:
            current[1].append(line)

    if current is not None:
        entries.append(current)

    return [(number, "\n".join(lines)) for number, lines in entries]


def parse_entry(number: int, raw_block: str) -> dict:
    block = collapse(raw_block)
    code_match = CODE_RE.search(block)
    code_labo = code_match.group(0) if code_match else None

    if code_match:
        name_raw = block[: code_match.start()]
        price = parse_price(block[code_match.end() :])
    else:
        price_match = PRICE_RE.search(block)
        name_raw = block[: price_match.start()] if price_match else block
        price = parse_price(block)

    name = collapse(name_raw).strip(" -")
    active = price is not None and bool(name)

    return {
        "code_element": f"BIO-{number:03d}",
        "code_labo": code_labo,
        "type": "Analyse",
        "nom": name or f"Examen biologique {number}",
        "service": "Laboratoire",
        "montant_fcfa": price or 0,
        "hopital_id": "HSJ-229",
        "actif": active,
        "metadata_json": {
            "numero_catalogue": number,
            "raw_source": raw_block,
            "source_file": "catalogue.tex",
        },
    }
