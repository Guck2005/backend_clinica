import re
from typing import Literal


OperatorCode = Literal["MTN", "MOOV", "CELTIIS"]


_PREFIX_TO_OPERATOR: dict[str, OperatorCode] = {
    "40": "CELTIIS",
    "41": "CELTIIS",
    "42": "MTN",
    "43": "CELTIIS",
    "44": "CELTIIS",
    "45": "MOOV",
    "46": "MTN",
    "47": "CELTIIS",
    "50": "MTN",
    "51": "MTN",
    "52": "MTN",
    "53": "MTN",
    "54": "MTN",
    "55": "MOOV",
    "56": "MTN",
    "57": "MTN",
    "58": "MOOV",
    "59": "MTN",
    "60": "MOOV",
    "61": "MTN",
    "62": "MTN",
    "63": "MOOV",
    "64": "MOOV",
    "65": "MOOV",
    "66": "MTN",
    "67": "MTN",
    "68": "MOOV",
    "69": "MTN",
    "90": "MTN",
    "91": "MTN",
    "94": "MOOV",
    "95": "MOOV",
    "96": "MTN",
    "97": "MTN",
    "98": "MOOV",
    "99": "MOOV",
}


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", phone or "")
    if len(digits) == 8:
        return f"229{digits}"
    if len(digits) == 10 and digits.startswith("01"):
        return f"229{digits}"
    return digits


def format_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    if len(normalized) == 11 and normalized.startswith("229"):
        local = normalized[3:]
        parts = [local[index:index + 2] for index in range(0, len(local), 2)]
        return f"+229 {' '.join(parts)}"
    if len(normalized) == 13 and normalized.startswith("22901"):
        local = normalized[3:]
        parts = [local[index:index + 2] for index in range(0, len(local), 2)]
        return f"+229 {' '.join(parts)}"
    return phone.strip()


def extract_benin_local_phone(phone: str) -> str | None:
    normalized = normalize_phone(phone)
    if len(normalized) == 11 and normalized.startswith("229"):
        return normalized[3:]
    if len(normalized) == 13 and normalized.startswith("22901"):
        return normalized[3:]
    if len(normalized) in {8, 10}:
        return normalized
    return None


def deduce_benin_mobile_operator(phone: str) -> OperatorCode | None:
    local = extract_benin_local_phone(phone)
    if not local:
        return None
    if len(local) == 10 and local.startswith("01"):
        prefix = local[2:4]
    else:
        prefix = local[:2]
    return _PREFIX_TO_OPERATOR.get(prefix)

