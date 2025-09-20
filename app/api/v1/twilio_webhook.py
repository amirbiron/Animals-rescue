"""
Twilio inbound webhook (SMS/WhatsApp) to capture organization responses.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

import structlog
from fastapi import APIRouter, Form, HTTPException, Request

from app.core.config import settings
from app.models.database import (
    async_session_maker, Alert, AlertStatus, Organization, Report, ReportStatus
)
from sqlalchemy import select

logger = structlog.get_logger(__name__)

router = APIRouter()


def _normalize_from_number(sender: Optional[str]) -> Optional[str]:
    """Twilio sends From like '+972…' (SMS) או 'whatsapp:+972…' (WA)."""
    if not sender:
        return sender
    s = sender.strip()
    if s.startswith("whatsapp:"):
        s = s.replace("whatsapp:", "", 1)
    return s


def _parse_decision(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower()
    # Hebrew/English short confirmations
    if t in {"ק", "כן", "מאשר", "אקבל", "אקח", "accept", "yes", "1"}:
        return "accept"
    if t in {"ר", "לא", "דוחה", "לא זמין", "reject", "no", "2"}:
        return "reject"
    return None


@router.post("/inbound")
async def twilio_inbound(
    request: Request,
    From: str = Form(...),
    Body: str = Form("")
) -> Dict[str, Any]:
    """
    Handle inbound SMS/WhatsApp messages.
    We map the sender phone to Organization.primary_phone and the latest pending Alert,
    then record the decision (accept/reject) by updating the related Report.
    """
    try:
        # Validate Twilio signature
        signature = request.headers.get("X-Twilio-Signature")
        try:
            from twilio.request_validator import RequestValidator  # type: ignore
        except Exception as e:
            logger.error("Twilio validator import failed", error=str(e))
            raise HTTPException(status_code=500, detail="Twilio validator unavailable")

        form = await request.form()
        params = {k: v for k, v in form.items()}
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN or "")
        url_current = str(request.url)

        def _validate(sig_url: str) -> bool:
            try:
                return bool(validator.validate(sig_url, params, signature or ""))
            except Exception:
                return False

        if not signature or not _validate(url_current):
            # Some deployments need external host for validation
            alt_url = None
            if settings.WEBHOOK_HOST:
                alt_url = f"{settings.WEBHOOK_HOST.rstrip('/')}{request.url.path}"
                if request.url.query:
                    alt_url = f"{alt_url}?{request.url.query}"
            if not (alt_url and _validate(alt_url)):
                logger.warning("Twilio signature validation failed", url=url_current)
                raise HTTPException(status_code=401, detail="Invalid signature")

        sender = _normalize_from_number(From)
        decision = _parse_decision(Body)
        logger.info("Twilio inbound", sender=sender, decision=decision)

        if not sender:
            raise HTTPException(status_code=400, detail="Missing sender")

        async with async_session_maker() as session:
            # Find organization by phone
            org_result = await session.execute(
                select(Organization).where(Organization.primary_phone.ilike(f"%{sender}%"))
            )
            organization = org_result.scalar_one_or_none()
            if not organization:
                return {"status": "ignored", "reason": "organization_not_found"}

            # Find the most recent alert to this organization in the last day
            alert_result = await session.execute(
                select(Alert)
                .where(Alert.organization_id == organization.id)
                .order_by(Alert.created_at.desc())
                .limit(1)
            )
            alert = alert_result.scalar_one_or_none()
            if not alert:
                return {"status": "ignored", "reason": "alert_not_found"}

            # Load report
            report_result = await session.execute(
                select(Report).where(Report.id == alert.report_id)
            )
            report = report_result.scalar_one_or_none()
            if not report:
                return {"status": "ignored", "reason": "report_not_found"}

            # Apply decision
            if decision == "accept":
                # Organization acknowledges and takes report
                report.status = ReportStatus.ACKNOWLEDGED
                report.assigned_organization_id = organization.id
                alert.status = AlertStatus.DELIVERED
                await session.commit()
                return {"status": "ok", "action": "accepted", "report": str(report.id)}
            elif decision == "reject":
                # Explicit rejection; leave report pending but note failure
                alert.status = AlertStatus.REJECTED
                await session.commit()
                return {"status": "ok", "action": "rejected", "report": str(report.id)}
            else:
                # No clear decision -> ignore but 200 OK to Twilio
                return {"status": "ignored", "reason": "no_decision"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Twilio inbound failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to process inbound message")

