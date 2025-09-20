"""
WhatsApp service (Twilio) for sending alerts via WhatsApp Business API (Twilio sandbox/number).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import structlog

from app.core.config import settings
from app.core.exceptions import ConfigurationError

logger = structlog.get_logger(__name__)


def _normalize_whatsapp_number(phone: str) -> str:
    if not phone:
        return phone
    phone = phone.strip()
    # Ensure E.164 with +, then add whatsapp: prefix
    if phone.startswith("00") and "+" not in phone:
        phone = "+" + phone[2:]
    if phone.startswith("0") and not phone.startswith("+"):
        phone = "+972" + phone[1:]
    if not phone.startswith("whatsapp:"):
        phone = f"whatsapp:{phone}"
    return phone


@dataclass
class WhatsAppResult:
    status: str
    external_id: Optional[str] = None
    error: Optional[str] = None


class TwilioWhatsApp:
    def __init__(self) -> None:
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM):
            raise ConfigurationError("TwilioWhatsApp", "Missing TWILIO_* env vars for WhatsApp")
        try:
            from twilio.rest import Client  # type: ignore
        except Exception as exc:
            raise ConfigurationError("TwilioWhatsApp", f"Twilio client not installed: {exc}")
        self._Client = Client
        # Must be in form whatsapp:+972...
        from_number = settings.TWILIO_WHATSAPP_FROM
        if not from_number.startswith("whatsapp:"):
            from_number = f"whatsapp:{from_number}"
        self._from = from_number

    async def send(self, to_phone: str, body: str) -> WhatsAppResult:
        loop = asyncio.get_event_loop()

        def _send_sync() -> WhatsAppResult:
            try:
                client = self._Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                message = client.messages.create(
                    body=body,
                    from_=self._from,
                    to=_normalize_whatsapp_number(to_phone),
                )
                return WhatsAppResult(status="success", external_id=message.sid)
            except Exception as e:
                logger.error("Twilio WhatsApp send failed", error=str(e))
                return WhatsAppResult(status="failed", error=str(e))

        return await loop.run_in_executor(None, _send_sync)


_wa_service: Optional[TwilioWhatsApp] = None


def get_whatsapp_service() -> TwilioWhatsApp:
    global _wa_service
    if _wa_service is None:
        _wa_service = TwilioWhatsApp()
    return _wa_service

