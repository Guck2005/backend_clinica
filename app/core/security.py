import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.config import settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${_b64url(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations_raw, salt, digest = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(_b64url(expected), digest)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + settings.access_token_minutes * 60,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([
        _b64url(json.dumps(header, separators=(",", ":")).encode()),
        _b64url(json.dumps(payload, separators=(",", ":")).encode()),
    ])
    signature = hmac.new(settings.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        header_raw, payload_raw, signature_raw = token.split(".", 2)
        signing_input = f"{header_raw}.{payload_raw}"
        expected = hmac.new(settings.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), signature_raw):
            return None
        payload = json.loads(_b64url_decode(payload_raw))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except (ValueError, json.JSONDecodeError, TypeError):
        return None
