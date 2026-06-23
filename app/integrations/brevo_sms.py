from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class SmsProviderError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class SmsSendResult:
    status: str
    provider: str
    message_id: str | None = None


class SmsProvider(Protocol):
    def send_sms(self, *, recipient: str, content: str) -> SmsSendResult: ...


class BrevoSmsProvider:
    def __init__(self, *, api_key: str, sender: str, base_url: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.sender = sender
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def send_sms(self, *, recipient: str, content: str) -> SmsSendResult:
        if not self.api_key or not self.sender:
            raise SmsProviderError("Configuration Brevo incomplete.")

        payload = {
            "sender": self.sender,
            "recipient": recipient,
            "content": content,
            "type": "transactional",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/transactionalSMS/sms",
                    headers={
                        "api-key": self.api_key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise SmsProviderError("Impossible de contacter Brevo pour le moment.") from exc

        if response.status_code >= 400:
            detail = response.text.strip() or "Erreur Brevo."
            raise SmsProviderError(detail)

        try:
            data = response.json()
        except ValueError as exc:
            raise SmsProviderError("Reponse Brevo invalide.") from exc

        message_id = None
        if isinstance(data, dict):
            for key in ("messageId", "message_id", "id"):
                value = data.get(key)
                if value not in {None, ""}:
                    message_id = str(value)
                    break

        return SmsSendResult(status="ENVOYE", provider="BREVO", message_id=message_id)


class LocalSmsLoggerProvider:
    def send_sms(self, *, recipient: str, content: str) -> SmsSendResult:
        logger.info("Invoice SMS local log to %s: %s", recipient, content)
        return SmsSendResult(status="LOCAL_LOG", provider="LOCAL_LOG")


def get_sms_provider() -> SmsProvider:
    if settings.brevo_api_key and settings.brevo_sms_sender:
        return BrevoSmsProvider(
            api_key=settings.brevo_api_key,
            sender=settings.brevo_sms_sender,
            base_url=settings.brevo_base_url,
            timeout_seconds=settings.brevo_timeout_seconds,
        )
    return LocalSmsLoggerProvider()
