"""
SMS service (Twilio) for sending emergency alerts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any

import structlog

from app.core.config import settings
from app.core.exceptions import ConfigurationError, ExternalServiceError

logger = structlog.get_logger(__name__)


def _normalize_e164(phone: str) -> str:
    """Minimal normalization to E.164 (assumes input already near-correct)."""
    if not phone:
        return phone
    phone = phone.strip()
    # If starts with 0 and looks Israeli, convert to +972
    if phone.startswith("0") and not phone.startswith("00") and "+" not in phone:
        # remove leading 0
        return "+972" + phone[1:]
    if phone.startswith("00") and "+" not in phone:
        return "+" + phone[2:]
    return phone


@dataclass
class SmsResult:
    status: str
    external_id: Optional[str] = None
    error: Optional[str] = None


class TwilioSMS:
    """Thin async wrapper around Twilio REST client for SMS sending."""

    def __init__(self) -> None:
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_SMS_FROM):
            raise ConfigurationError("Twilio", "Missing TWILIO_* environment variables")
        # Lazy import to avoid import at startup if unused
        try:
            from twilio.rest import Client  # type: ignore
        except Exception as exc:
            raise ConfigurationError("Twilio", f"Twilio client not installed: {exc}")
        self._Client = Client
        self._from = settings.TWILIO_SMS_FROM

    async def send(self, to_phone: str, body: str) -> SmsResult:
        loop = asyncio.get_event_loop()

        def _send_sync() -> SmsResult:
            try:
                client = self._Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=body,
                    from_=self._from,
                    to=_normalize_e164(to_phone),
                )
                return SmsResult(status="success", external_id=message.sid)
            except Exception as e:
                logger.error("Twilio SMS send failed", error=str(e))
                return SmsResult(status="failed", error=str(e))

        return await loop.run_in_executor(None, _send_sync)


# Global instance helper (created on demand)
_sms_service: Optional[TwilioSMS] = None


def get_sms_service() -> TwilioSMS:
    global _sms_service
    if _sms_service is None:
        _sms_service = TwilioSMS()
    return _sms_service

