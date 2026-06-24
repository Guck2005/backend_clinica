from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import settings
from app.core.phone import OperatorCode, extract_benin_local_phone


class FedaPayProviderError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class FedaPayInitiationResult:
    provider_attempt_id: str
    provider_status: str
    operator_code: OperatorCode
    phone_number: str
    raw_payload: dict[str, Any]


@dataclass
class FedaPayStatusResult:
    provider_attempt_id: str
    provider_status: str
    reference_paiement: str | None
    raw_payload: dict[str, Any]


def _extract_resource(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("v1/transaction", "transaction", "data", "entity"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _extract_identifier(payload: Any) -> str | None:
    resource = _extract_resource(payload)
    value = resource.get("id") or payload.get("id") if isinstance(payload, dict) else None
    if value in {None, ""}:
        return None
    return str(value)


def _extract_status(payload: Any) -> str | None:
    resource = _extract_resource(payload)
    value = resource.get("status") or resource.get("state")
    if value is None:
        return None
    return str(value).strip().lower()


def _extract_payment_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    if isinstance(token, str) and token.strip():
        return token.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("token")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


def _extract_reference(payload: Any) -> str | None:
    resource = _extract_resource(payload)
    for key in ("reference", "transaction_id", "provider_reference", "reference_number", "id"):
        value = resource.get(key)
        if value not in {None, ""}:
            return str(value)
    return None


def _extract_int(payload: Any, key: str) -> int | None:
    resource = _extract_resource(payload)
    value = resource.get(key)
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_error_code(payload: Any) -> str | None:
    resource = _extract_resource(payload)
    value = resource.get("last_error_code")
    if value in {None, ""}:
        return None
    return str(value)


def extract_provider_mode(payload: Any) -> str | None:
    resource = _extract_resource(payload)
    value = resource.get("mode")
    if value in {None, ""}:
        return None
    return str(value)


def extract_amount_debited(payload: Any) -> int | None:
    return _extract_int(payload, "amount_debited")


def extract_provider_fees(payload: Any) -> int | None:
    return _extract_int(payload, "fees")


class FedaPayProvider:
    def __init__(
        self,
        *,
        secret_key: str,
        base_url: str,
        webhook_secret: str,
        timeout_seconds: int,
        methods_by_operator: dict[OperatorCode, str],
    ) -> None:
        self.secret_key = secret_key.strip()
        self.base_url = base_url.rstrip("/")
        self.webhook_secret = webhook_secret.strip()
        self.timeout_seconds = timeout_seconds
        self.methods_by_operator = methods_by_operator

    def _headers(self) -> dict[str, str]:
        if not self.secret_key:
            raise FedaPayProviderError(
                "Configuration FedaPay incomplete: FEDAPAY_SECRET_KEY manquant.",
                status_code=503,
            )
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, headers=self._headers(), json=json_body)
        except httpx.HTTPError as exc:
            raise FedaPayProviderError("Impossible de contacter FedaPay pour le moment.") from exc

        if response.status_code >= 400:
            detail = response.text.strip() or "Erreur FedaPay."
            raise FedaPayProviderError(detail, status_code=502)

        try:
            payload = response.json()
        except ValueError as exc:
            raise FedaPayProviderError("Reponse FedaPay invalide.") from exc

        if not isinstance(payload, dict):
            raise FedaPayProviderError("Reponse FedaPay inattendue.")
        return payload

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        if not self.webhook_secret or not signature_header:
            return False

        header = signature_header.strip()

        if "t=" in header and "s=" in header:
            try:
                parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
                t = parts.get("t")
                s = parts.get("s")
                if t and s:
                    signed_payload = f"{t}.{raw_body.decode('utf-8')}".encode("utf-8")
                    expected = hmac.new(
                        self.webhook_secret.encode("utf-8"),
                        signed_payload,
                        hashlib.sha256,
                    ).hexdigest()
                    if hmac.compare_digest(expected, s):
                        return True
            except Exception:
                pass

        # Fallback pour l'ancien format / payload pur
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        provided = header
        if provided.startswith("sha256="):
            provided = provided.split("=", 1)[1]
        return hmac.compare_digest(expected, provided)

    def start_mobile_money_payment(
        self,
        *,
        amount_fcfa: int,
        description: str,
        merchant_reference: str,
        operator_code: OperatorCode,
        phone_number: str,
        metadata: dict[str, Any],
    ) -> FedaPayInitiationResult:
        local_phone = extract_benin_local_phone(phone_number)
        if local_phone is None:
            raise FedaPayProviderError("Numero patient invalide pour FedaPay.", status_code=422)

        collection_payload = {
            "description": description,
            "amount": amount_fcfa,
            "currency": {"iso": "XOF"},
            "merchant_reference": merchant_reference,
            "custom_metadata": metadata,
        }
        created = self._request("POST", "/v1/transactions", json_body=collection_payload)
        provider_attempt_id = _extract_identifier(created)
        if provider_attempt_id is None:
            raise FedaPayProviderError("FedaPay n'a pas retourne d'identifiant de collecte.")

        token_payload = self._request("POST", f"/v1/transactions/{provider_attempt_id}/token")
        token = _extract_payment_token(token_payload)
        if token is None:
            raise FedaPayProviderError("FedaPay n'a pas retourne de token de paiement.")

        operator_path = self.methods_by_operator[operator_code]
        trigger_payload = {
            "token": token,
            "phone_number": {
                "number": local_phone,
                "country": "bj",
            },
        }
        triggered = self._request("POST", f"/v1/{operator_path}", json_body=trigger_payload)
        provider_status = _extract_status(triggered) or _extract_status(created) or "pending"

        return FedaPayInitiationResult(
            provider_attempt_id=provider_attempt_id,
            provider_status=provider_status,
            operator_code=operator_code,
            phone_number=phone_number,
            raw_payload={
                "collection": created,
                "token": token_payload,
                "trigger": triggered,
            },
        )

    def fetch_transaction_status(self, provider_attempt_id: str) -> FedaPayStatusResult:
        payload = self._request("GET", f"/v1/transactions/{provider_attempt_id}")
        normalized_status = _extract_status(payload) or "pending"
        return FedaPayStatusResult(
            provider_attempt_id=provider_attempt_id,
            provider_status=normalized_status,
            reference_paiement=_extract_reference(payload),
            raw_payload=payload,
        )

    def extract_webhook_transaction_id(self, payload: dict[str, Any]) -> str | None:
        candidates = [
            _extract_identifier(payload),
            _extract_identifier(payload.get("entity")) if isinstance(payload.get("entity"), dict) else None,
            _extract_identifier(payload.get("data")) if isinstance(payload.get("data"), dict) else None,
        ]
        for value in candidates:
            if value:
                return value
        return None


@lru_cache
def get_fedapay_provider() -> FedaPayProvider:
    return FedaPayProvider(
        secret_key=settings.fedapay_secret_key,
        base_url=settings.fedapay_base_url,
        webhook_secret=settings.fedapay_webhook_secret,
        timeout_seconds=settings.fedapay_timeout_seconds,
        methods_by_operator={
            "MTN": settings.fedapay_method_mtn,
            "MOOV": settings.fedapay_method_moov,
            "CELTIIS": settings.fedapay_method_celtiis,
        },
    )
