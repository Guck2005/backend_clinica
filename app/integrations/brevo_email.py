from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmailProviderError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class EmailSendResult:
    status: str
    provider: str
    message_id: str | None = None


class EmailProvider(Protocol):
    def send_email(self, *, recipient: str, subject: str, html_content: str, text_content: str) -> EmailSendResult: ...


class BrevoEmailProvider:
    def __init__(self, *, api_key: str, sender: str, base_url: str, timeout_seconds: int) -> None:
        self.api_key = api_key
        self.sender = sender
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def send_email(self, *, recipient: str, subject: str, html_content: str, text_content: str) -> EmailSendResult:
        if not self.api_key or not self.sender:
            raise EmailProviderError("Configuration Brevo email incomplete.")

        payload = {
            "sender": {"email": self.sender},
            "to": [{"email": recipient}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url}/smtp/email",
                    headers={
                        "api-key": self.api_key,
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise EmailProviderError("Impossible de contacter Brevo pour l'envoi email.") from exc

        if response.status_code >= 400:
            raise EmailProviderError(response.text.strip() or "Erreur Brevo email.")

        try:
            data = response.json()
        except ValueError as exc:
            raise EmailProviderError("Reponse Brevo email invalide.") from exc

        message_id = None
        if isinstance(data, dict):
            value = data.get("messageId")
            if value not in {None, ""}:
                message_id = str(value)

        return EmailSendResult(status="ENVOYE", provider="BREVO", message_id=message_id)


class LocalEmailLoggerProvider:
    def send_email(self, *, recipient: str, subject: str, html_content: str, text_content: str) -> EmailSendResult:
        logger.info("Alert email local log to %s | %s | %s", recipient, subject, text_content)
        return EmailSendResult(status="LOCAL_LOG", provider="LOCAL_LOG")


def get_email_provider() -> EmailProvider:
    if settings.brevo_api_key and settings.brevo_email_from and settings.brevo_alert_email_to:
        return BrevoEmailProvider(
            api_key=settings.brevo_api_key,
            sender=settings.brevo_email_from,
            base_url=settings.brevo_base_url,
            timeout_seconds=settings.brevo_timeout_seconds,
        )
    return LocalEmailLoggerProvider()
