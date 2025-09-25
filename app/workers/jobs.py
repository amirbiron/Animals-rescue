"""
Background Job Workers
עובדי רקע למטלות אסינכרוניות

This module contains all background job workers using RQ (Redis Queue) for 
asynchronous task processing in the Animal Rescue Bot system.
"""

import asyncio
import os
import json
import smtplib
import uuid
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rq import Retry, get_current_job
from rq.decorators import job
from sqlalchemy import select, update, and_, or_
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.cache import redis_client, redis_queue_sync
from app.models.database import (
    async_session_maker, User, Organization, Report, Alert, Event,
    ReportStatus, AlertStatus, AlertChannel, EventType, UrgencyLevel,
    AnimalType, OrganizationType, create_point_from_coordinates
)
from app.services.google import GoogleService
from app.services.serpapi import SerpAPIService
from app.services.nlp import NLPService
from app.services.email import EmailService
from app.services.telegram_alerts import TelegramAlertsService
from app.services.whatsapp import get_whatsapp_service
from app.services.sms import get_sms_service
from app.services.sms import _normalize_e164 as _normalize_phone_e164
from app.core.i18n import get_text

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# Service Initialization
# =============================================================================

google_service = GoogleService()
serpapi_service = SerpAPIService()
nlp_service = NLPService()
email_service = EmailService()
telegram_alerts = TelegramAlertsService()

# =============================================================================
# Report Processing Jobs
# =============================================================================

@job("default", timeout="10m", retry=Retry(max=3, interval=60), connection=redis_queue_sync)
def process_new_report(report_id: str) -> Dict[str, Any]:
    """
    Process a newly submitted report.
    
    This job performs all necessary background processing for a new report:
    - Enhanced geocoding and location validation
    - Find nearby organizations
    - Enhanced NLP analysis
    - Generate report summary
    - Create audit events
    
    Args:
        report_id: UUID string of the report to process
        
    Returns:
        Processing results dictionary
    """
    job = get_current_job()
    job_id = getattr(job, "id", None)
    logger.info("Processing new report", report_id=report_id, job_id=job_id)
    
    try:
        # Use asyncio for async database operations
        return asyncio.run(_process_new_report_async(report_id))
        
    except Exception as e:
        logger.error(
            "Failed to process new report",
            report_id=report_id,
            error=str(e),
            exc_info=True
        )
        # Re-raise for RQ retry mechanism
        raise


async def _process_new_report_async(report_id: str) -> Dict[str, Any]:
    """Async implementation of report processing."""
    results = {
        "report_id": report_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "steps_completed": [],
        "errors": [],
        "organizations_found": 0,
        "alerts_created": 0,
    }
    
    async with async_session_maker() as session:
        # Get report with related data
        result = await session.execute(
            select(Report)
            .options(selectinload(Report.reporter))
            .where(Report.id == uuid.UUID(report_id))
        )
        report = result.scalar_one_or_none()
        
        if not report:
            raise ValueError(f"Report {report_id} not found")
        
        logger.info(
            "Found report for processing",
            report_id=report_id,
            public_id=report.public_id,
            urgency=report.urgency_level.value,
            animal_type=report.animal_type.value
        )
        
        # Step 1: Enhanced location processing
        if report.latitude and report.longitude and not report.address_verified:
            try:
                # Reverse geocode to get detailed address
                location_details = await google_service.reverse_geocode(
                    report.latitude, report.longitude
                )
                
                if location_details:
                    report.address = location_details.get("formatted_address", report.address)
                    report.city = location_details.get("city", report.city)
                    report.address_verified = True
                    results["steps_completed"].append("enhanced_geocoding")
                    
            except Exception as e:
                logger.warning("Enhanced geocoding failed", error=str(e))
                results["errors"].append(f"Enhanced geocoding: {str(e)}")
        
        # Step 2: Find nearby organizations
        organizations = []
        if report.latitude and report.longitude:
            try:
                # Search for organizations using multiple strategies
                organizations.extend(await _find_organizations_by_location(
                    report.latitude, report.longitude, report.urgency_level
                ))
                
                organizations.extend(await _find_organizations_by_type(
                    report.animal_type, report.city
                ))
                
                # Remove duplicates
                seen_ids = set()
                unique_orgs = []
                for org in organizations:
                    if org.id not in seen_ids:
                        unique_orgs.append(org)
                        seen_ids.add(org.id)
                
                organizations = unique_orgs
                results["organizations_found"] = len(organizations)
                results["steps_completed"].append("organization_search")
                
            except Exception as e:
                logger.error("Organization search failed", error=str(e))
                results["errors"].append(f"Organization search: {str(e)}")
        
        # Step 3: Enhanced NLP analysis
        try:
            # Perform advanced text analysis
            nlp_results = await nlp_service.analyze_report_content(
                text=report.description,
                language=report.language,
                context={
                    "location": report.city,
                    "urgency": report.urgency_level.value,
                    "animal_type": report.animal_type.value
                }
            )
            
            # Update report with enhanced analysis
            if nlp_results.get("keywords"):
                report.keywords = list(set(report.keywords + nlp_results["keywords"]))
            
            if nlp_results.get("sentiment") is not None:
                report.sentiment_score = nlp_results["sentiment"]
            
            # Check for duplicate detection
            if nlp_results.get("similar_reports"):
                await _check_for_duplicates(session, report, nlp_results["similar_reports"])
            
            results["steps_completed"].append("enhanced_nlp")
            
        except Exception as e:
            logger.warning("Enhanced NLP analysis failed", error=str(e))
            results["errors"].append(f"Enhanced NLP: {str(e)}")
        
        # Step 4: Update report status
        if not report.is_duplicate and organizations:
            report.status = ReportStatus.PENDING
            results["steps_completed"].append("status_update")
        
        # Step 5: Create audit event
        event = Event(
            event_type=EventType.REPORT_CREATED,
            entity_type="report",
            entity_id=report.id,
            user_id=report.reporter_id,
            payload={
                "report_id": str(report.id),
                "public_id": report.public_id,
                "urgency_level": report.urgency_level.value,
                "animal_type": report.animal_type.value,
                "organizations_found": len(organizations),
                "processing_results": results,
            }
        )
        session.add(event)
        
        await session.commit()
        
        # Step 6: Queue alert jobs for each organization
        if organizations and not report.is_duplicate:
            for org in organizations:
                # Create alert jobs for each channel
                for channel in org.alert_channels:
                    if settings.ENABLE_WORKERS:
                        send_organization_alert.delay(
                            report_id=report_id,
                            organization_id=str(org.id),
                            channel=channel
                        )
                    else:
                        # Run inline in background so we don't block
                        asyncio.create_task(_send_organization_alert_async(
                            report_id, str(org.id), channel
                        ))
                    results["alerts_created"] += 1
            
            results["steps_completed"].append("alerts_queued")
    
    logger.info(
        "Report processing completed",
        report_id=report_id,
        results=results
    )
    
    return results


@job("maintenance", timeout="5m", connection=redis_queue_sync)
def reconcile_alert_channels() -> Dict[str, int]:
    """Ensure each organization's alert_channels reflect available contact methods.

    - If organization.email exists, include 'email'
    - If organization.primary_phone exists, include 'sms' and 'whatsapp'
    - If organization.telegram_chat_id exists, include 'telegram'
    - Preserve order preference: whatsapp, sms, email, telegram
    """
    logger.info("Reconciling organization alert channels")
    try:
        return asyncio.run(_reconcile_alert_channels_async())
    except Exception as e:
        logger.error("reconcile_alert_channels failed", error=str(e))
        raise


async def _reconcile_alert_channels_async() -> Dict[str, int]:
    results = {"processed": 0, "updated": 0}
    async with async_session_maker() as session:
        orgs = (await session.execute(select(Organization))).scalars().all()
        for org in orgs:
            results["processed"] += 1
            desired: list[str] = []
            if org.primary_phone:
                desired.extend(["whatsapp", "sms"])  # prefer WhatsApp first
            if org.email:
                desired.append("email")
            if org.telegram_chat_id:
                desired.append("telegram")
            # Remove duplicates preserving order
            seen = set()
            desired_unique = [c for c in desired if not (c in seen or seen.add(c))]
            current = list(org.alert_channels or [])
            if desired_unique != current:
                org.alert_channels = desired_unique or current
                results["updated"] += 1
        await session.commit()
    logger.info("reconcile_alert_channels completed", **results)
    return results

async def _find_organizations_by_location(
    latitude: float, longitude: float, urgency: UrgencyLevel
) -> List[Organization]:
    """Find organizations near the incident location."""
    organizations = []
    
    async with async_session_maker() as session:
        # Calculate search radius based on urgency
        base_radius = settings.SEARCH_RADIUS_KM
        radius_multiplier = {
            UrgencyLevel.CRITICAL: 2.0,
            UrgencyLevel.HIGH: 1.5,
            UrgencyLevel.MEDIUM: 1.0,
            UrgencyLevel.LOW: 0.8,
        }
        search_radius = min(
            base_radius * radius_multiplier[urgency],
            settings.MAX_SEARCH_RADIUS_KM
        )
        
        # Database search using Haversine formula approximation
        result = await session.execute(
            select(Organization)
            .where(
                and_(
                    Organization.is_active == True,
                    Organization.latitude.isnot(None),
                    Organization.longitude.isnot(None),
                    # Approximate distance filter (more precise calculation done in Python)
                    and_(
                        Organization.latitude.between(
                            latitude - search_radius/111, 
                            latitude + search_radius/111
                        ),
                        Organization.longitude.between(
                            longitude - search_radius/(111*0.7),  # Rough correction for longitude
                            longitude + search_radius/(111*0.7)
                        )
                    )
                )
            )
            .limit(20)  # Limit initial results
        )
        
        candidates = result.scalars().all()
        
        # Calculate exact distances and filter
        for org in candidates:
            distance = _calculate_distance_km(
                latitude, longitude, org.latitude, org.longitude
            )
            
            if distance <= search_radius:
                org._distance = distance  # Store for sorting
                organizations.append(org)
        
        # Sort by distance and urgency matching
        organizations.sort(key=lambda o: (
            o._distance,
            0 if o.is_24_7 and urgency in [UrgencyLevel.CRITICAL, UrgencyLevel.HIGH] else 1
        ))
    
    return organizations[:10]  # Return top 10


async def _find_organizations_by_type(
    animal_type: AnimalType, city: Optional[str]
) -> List[Organization]:
    """Find organizations that specialize in the specific animal type."""
    organizations = []
    
    async with async_session_maker() as session:
        # Build query conditions
        conditions = [Organization.is_active == True]
        
        # Add city filter if available
        if city:
            conditions.append(Organization.city.ilike(f"%{city}%"))
        
        # Add specialty filter
        animal_keywords = {
            AnimalType.DOG: ["dog", "dogs", "כלב", "כלבים"],
            AnimalType.CAT: ["cat", "cats", "חתול", "חתולים"], 
            AnimalType.BIRD: ["bird", "birds", "צפור", "צפורים"],
            AnimalType.WILDLIFE: ["wildlife", "wild", "חיות בר"],
        }
        
        if animal_type in animal_keywords:
            keywords = animal_keywords[animal_type]
            specialty_conditions = []
            for keyword in keywords:
                specialty_conditions.append(
                    Organization.specialties.any(keyword)
                )
            
            if specialty_conditions:
                conditions.append(or_(*specialty_conditions))
        
        result = await session.execute(
            select(Organization)
            .where(and_(*conditions))
            .limit(10)
        )
        
        organizations = result.scalars().all()
    
    return organizations


async def _check_for_duplicates(
    session, report: Report, similar_reports: List[Dict[str, Any]]
) -> None:
    """Check if the report is a duplicate of existing reports."""
    
    # Time window for duplicate detection (1 hour)
    time_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
    
    for similar in similar_reports:
        if similar.get("confidence", 0) > 0.8:  # High confidence threshold
            # Check if there's a recent report in the same location
            result = await session.execute(
                select(Report)
                .where(
                    and_(
                        Report.id != report.id,
                        Report.created_at > time_threshold,
                        Report.latitude.between(
                            report.latitude - 0.001,  # ~100m radius
                            report.latitude + 0.001
                        ),
                        Report.longitude.between(
                            report.longitude - 0.001,
                            report.longitude + 0.001
                        ),
                        Report.animal_type == report.animal_type
                    )
                )
            )
            
            existing_report = result.scalar_one_or_none()
            if existing_report:
                report.is_duplicate = True
                report.duplicate_of_id = existing_report.id
                report.status = ReportStatus.DUPLICATE
                
                logger.info(
                    "Report marked as duplicate",
                    report_id=str(report.id),
                    duplicate_of=str(existing_report.id),
                    confidence=similar["confidence"]
                )
                break


def _calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points using Haversine formula."""
    import math
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat/2)**2 + 
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2)
    c = 2 * math.asin(math.sqrt(a))
    
    # Earth's radius in kilometers
    return 6371 * c


# =============================================================================
# Alert and Notification Jobs
# =============================================================================

@job("alerts", timeout="5m", retry=Retry(max=3, interval=30), connection=redis_queue_sync)
def send_organization_alert(
    report_id: str, organization_id: str, channel: str
) -> Dict[str, Any]:
    """
    Send alert to organization about a new report.
    
    Args:
        report_id: Report UUID string
        organization_id: Organization UUID string
        channel: Alert channel (telegram, email, sms, etc.)
        
    Returns:
        Alert sending results
    """
    job = get_current_job()
    job_id = getattr(job, "id", None)
    logger.info(
        "Sending organization alert",
        report_id=report_id,
        organization_id=organization_id,
        channel=channel,
        job_id=job_id
    )
    
    try:
        return asyncio.run(_send_organization_alert_async(
            report_id, organization_id, channel
        ))
        
    except Exception as e:
        logger.error(
            "Failed to send organization alert",
            report_id=report_id,
            organization_id=organization_id,
            channel=channel,
            error=str(e),
            exc_info=True
        )
        raise


async def _send_organization_alert_async(
    report_id: str, organization_id: str, channel: str
) -> Dict[str, Any]:
    """Async implementation of organization alert sending."""
    
    async with async_session_maker() as session:
        # Get report and organization data
        report_result = await session.execute(
            select(Report)
            .options(selectinload(Report.reporter))
            .where(Report.id == uuid.UUID(report_id))
        )
        report = report_result.scalar_one_or_none()
        
        org_result = await session.execute(
            select(Organization)
            .where(Organization.id == uuid.UUID(organization_id))
        )
        organization = org_result.scalar_one_or_none()
        
        if not report or not organization:
            raise ValueError("Report or organization not found")
        
        # Check if alert already exists
        existing_alert = await session.execute(
            select(Alert)
            .where(
                and_(
                    Alert.report_id == report.id,
                    Alert.organization_id == organization.id,
                    Alert.channel == AlertChannel(channel)
                )
            )
        )
        
        if existing_alert.scalar_one_or_none():
            logger.warning("Alert already exists", report_id=report_id, org_id=organization_id)
            return {"status": "duplicate", "message": "Alert already exists"}
        
        # Determine recipient based on channel
        recipient = None
        if channel == "telegram" and organization.telegram_chat_id:
            recipient = organization.telegram_chat_id
        elif channel == "email" and organization.email:
            recipient = organization.email
        elif channel == "sms" and organization.primary_phone:
            recipient = organization.primary_phone
        elif channel == "whatsapp" and organization.primary_phone:
            recipient = organization.primary_phone
        
        if not recipient:
            logger.warning(
                "No recipient found for alert channel",
                org_id=organization_id,
                channel=channel
            )
            return {"status": "failed", "message": f"No {channel} contact configured"}
        
        # Generate alert message
        message_data = await _generate_alert_message(report, organization, channel)
        
        # Create alert record
        alert = Alert(
            report_id=report.id,
            organization_id=organization.id,
            channel=AlertChannel(channel),
            recipient=recipient,
            subject=message_data.get("subject"),
            message=message_data["message"],
            message_template=message_data["template"],
            status=AlertStatus.QUEUED,
            max_attempts=3,
        )
        
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        
        # Send alert based on channel
        try:
            alert.status = AlertStatus.SENDING
            alert.attempts += 1
            await session.commit()
            
            result = None
            if channel == "telegram":
                result = await telegram_alerts.send_alert(
                    chat_id=recipient,
                    message=message_data["message"],
                    report=report,
                    organization=organization
                )
            elif channel == "email":
                result = await email_service.send_alert_email(
                    to_email=recipient,
                    subject=message_data["subject"],
                    content=message_data["message"],
                    report=report,
                    organization=organization
                )
            elif channel == "sms":
                try:
                    sms_service = get_sms_service()
                    sms_text = message_data["message"]
                    sms_res = await sms_service.send(recipient, sms_text)
                    result = {
                        "status": sms_res.status,
                        "external_id": sms_res.external_id,
                        "error": sms_res.error,
                    }
                except Exception as e:
                    result = {"status": "failed", "error": str(e)}
            elif channel == "whatsapp":
                try:
                    wa_service = get_whatsapp_service()
                    wa_text = message_data["message"]
                    wa_res = await wa_service.send(recipient, wa_text)
                    result = {
                        "status": wa_res.status,
                        "external_id": wa_res.external_id,
                        "error": wa_res.error,
                    }
                except Exception as e:
                    result = {"status": "failed", "error": str(e)}
            
            if result and result.get("status") == "success":
                alert.status = AlertStatus.SENT
                alert.sent_at = datetime.now(timezone.utc)
                alert.external_id = result.get("external_id")
            else:
                alert.status = AlertStatus.FAILED
                alert.last_error = result.get("error", "Unknown error")

                # Escalation: try next channel in org.alert_channels
                try:
                    channels = list(organization.alert_channels or [])
                    if channel in channels:
                        current_index = channels.index(channel)
                        if current_index + 1 < len(channels):
                            next_channel = channels[current_index + 1]
                            # Queue next channel immediately
                            if settings.ENABLE_WORKERS:
                                send_organization_alert.delay(
                                    str(report.id), str(organization.id), next_channel
                                )
                            else:
                                asyncio.create_task(_send_organization_alert_async(
                                    str(report.id), str(organization.id), next_channel
                                ))
                except Exception as _e:
                    logger.warning("Escalation scheduling failed", error=str(_e))

                # Also schedule retry if attempts remain
                if alert.attempts < alert.max_attempts:
                    retry_delay = min(alert.attempts * 60, 300)  # Max 5 min delay
                    alert.retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
                    alert.status = AlertStatus.QUEUED
            
            await session.commit()
            
            # Update metrics
            from app.main import ALERTS_SENT
            ALERTS_SENT.labels(
                channel=channel,
                status=alert.status.value
            ).inc()
            
            logger.info(
                "Alert sent",
                alert_id=str(alert.id),
                status=alert.status.value,
                channel=channel
            )
            
            return {
                "status": alert.status.value,
                "alert_id": str(alert.id),
                "external_id": alert.external_id,
                "attempts": alert.attempts,
            }
            
        except Exception as e:
            alert.status = AlertStatus.FAILED
            alert.last_error = str(e)
            
            # Schedule retry
            if alert.attempts < alert.max_attempts:
                retry_delay = min(alert.attempts * 60, 300)
                alert.retry_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay)
                alert.status = AlertStatus.QUEUED
            
            await session.commit()
            
            logger.error("Alert sending failed", error=str(e), alert_id=str(alert.id))
            raise


async def _generate_alert_message(
    report: Report, organization: Organization, channel: str
) -> Dict[str, str]:
    """Generate alert message content based on template."""
    
    # Load Jinja2 templates
    template_env = Environment(
        loader=FileSystemLoader("app/templates/alerts"),
        autoescape=select_autoescape(['html', 'xml'])
    )
    
    # Determine language (prefer organization's or use report language)
    lang = report.language
    
    # Template context
    context = {
        "report": report,
        "organization": organization,
        "urgency_text": get_text(f"urgency_{report.urgency_level.value}", lang),
        "animal_text": get_text(f"animal_{report.animal_type.value}", lang),
        "status_text": get_text(f"status_{report.status.value}", lang),
        "app_name": settings.APP_NAME,
        "emergency_phone": "1-800-ANIMAL",
        "report_url": f"https://app.animal-rescue.com/reports/{report.public_id}",
        "maps_url": f"https://maps.google.com/?q={report.latitude},{report.longitude}" if report.latitude else None,
    }
    
    # Select template based on channel
    template_name = f"alert_{channel}_{lang}.j2"
    try:
        template = template_env.get_template(template_name)
    except Exception:
        # Fallbacks for text-only channels (sms/whatsapp) when specific template missing
        if channel in {"sms", "whatsapp"}:
            # פולבאק טקסטואלי לערוצים פשוטים: WhatsApp/SMS
            urgency_icon = {
                UrgencyLevel.CRITICAL: "🚨",
                UrgencyLevel.HIGH: "🔴",
                UrgencyLevel.MEDIUM: "🟠",
                UrgencyLevel.LOW: "🟢",
            }.get(report.urgency_level, "📢")

            # טרימינג לתיאור קצר
            desc = (report.description or "").strip()
            if desc:
                if len(desc) > 180:
                    desc = desc[:177] + "…"

            # שם משתמש או טלפון של המדווח
            reporter_username = None
            reporter_phone = None
            try:
                reporter = getattr(report, 'reporter', None)
                reporter_username = getattr(reporter, 'username', None)
                reporter_phone = getattr(reporter, 'phone', None)
            except Exception:
                pass

            reporter_display = None
            if reporter_username:
                reporter_display = f"@{reporter_username}"
            elif reporter_phone:
                reporter_display = reporter_phone

            # עיר וקישור מפה
            city = report.city or ""
            maps_url = None
            if report.latitude and report.longitude:
                maps_url = f"https://maps.google.com/?q={report.latitude},{report.longitude}"

            # הודעה רב-שורתית, תואם לדוגמה המבוקשת
            lines: List[str] = []
            lines.append(f"{urgency_icon} {get_text('alert.new_report.body', lang)}!")
            lines.append(f"🔹 מזהה: #{report.public_id}")
            # סוג חיה
            try:
                animal_text = get_text(f"animal_{report.animal_type.value}", lang)
            except Exception:
                animal_text = str(report.animal_type.value).capitalize()
            lines.append(f"🔹 סוג חיה: {animal_text}")
            if desc:
                lines.append(f"🔹 תיאור: {desc}")
            if city:
                lines.append(f"🔹 מיקום: {city}")
            if maps_url:
                lines.append(f"📍 {maps_url}")
            if reporter_display:
                lines.append(f"👤 מדווח: {reporter_display}")
            # טלפון ארגון (לא חובה; לרוב זה אותו מספר שמקבל את ההודעה)
            try:
                org_phone = getattr(organization, 'primary_phone', None)
            except Exception:
                org_phone = None
            if org_phone:
                try:
                    org_phone_norm = _normalize_phone_e164(org_phone)
                except Exception:
                    org_phone_norm = org_phone
                lines.append(f"☎️ ארגון: {org_phone_norm}")

            text_message = "\n".join(lines)
            return {"message": text_message, "subject": None, "template": "inline_text_multiline"}
        # Else fallback to Hebrew template
        template_name = f"alert_{channel}_he.j2"
        template = template_env.get_template(template_name)
    
    # Render message
    message_content = template.render(**context)
    
    # Generate subject for email
    subject = None
    if channel == "email":
        urgency_emoji = {
            UrgencyLevel.CRITICAL: "🚨",
            UrgencyLevel.HIGH: "🔴",
            UrgencyLevel.MEDIUM: "🟡",
            UrgencyLevel.LOW: "🟢",
        }.get(report.urgency_level, "📢")
        
        subject = f"{urgency_emoji} {get_text('alert_subject', lang)} - {report.public_id}"
    
    return {
        "message": message_content,
        "subject": subject,
        "template": template_name,
    }


@job("alerts", timeout="2m", retry=Retry(max=2, interval=60), connection=redis_queue_sync)
def retry_failed_alerts() -> Dict[str, int]:
    """Retry failed alerts that are eligible for retry."""
    logger.info("Retrying failed alerts")
    
    try:
        return asyncio.run(_retry_failed_alerts_async())
    except Exception as e:
        logger.error("Failed to retry alerts", error=str(e))
        raise


async def _retry_failed_alerts_async() -> Dict[str, int]:
    """Async implementation of alert retry."""
    results = {"retried": 0, "skipped": 0, "failed": 0}
    
    async with async_session_maker() as session:
        # Find alerts eligible for retry
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(Alert)
            .where(
                and_(
                    Alert.status == AlertStatus.QUEUED,
                    Alert.retry_at <= now,
                    Alert.attempts < Alert.max_attempts
                )
            )
            .limit(50)  # Process in batches
        )
        
        alerts_to_retry = result.scalars().all()
        
        for alert in alerts_to_retry:
            try:
                # Queue the retry job
                if settings.ENABLE_WORKERS:
                    send_organization_alert.delay(
                        str(alert.report_id),
                        str(alert.organization_id),
                        alert.channel.value
                    )
                else:
                    asyncio.create_task(_send_organization_alert_async(
                        str(alert.report_id), str(alert.organization_id), alert.channel.value
                    ))
                results["retried"] += 1
                
            except Exception as e:
                logger.error(
                    "Failed to queue retry",
                    alert_id=str(alert.id),
                    error=str(e)
                )
                results["failed"] += 1
    
    logger.info("Alert retry completed", results=results)
    return results


# =============================================================================
# Cleanup and Maintenance Jobs
# =============================================================================

@job("maintenance", timeout="30m", connection=redis_queue_sync)
def cleanup_old_data() -> Dict[str, int]:
    """Clean up old data according to retention policies."""
    logger.info("Starting data cleanup")
    
    try:
        return asyncio.run(_cleanup_old_data_async())
    except Exception as e:
        logger.error("Data cleanup failed", error=str(e))
        raise


async def _cleanup_old_data_async() -> Dict[str, int]:
    """Async implementation of data cleanup."""
    results = {
        "reports_archived": 0,
        "files_deleted": 0,
        "events_cleaned": 0,
        "alerts_cleaned": 0,
    }
    
    async with async_session_maker() as session:
        # Clean up old completed reports
        expiry_date = datetime.now(timezone.utc) - timedelta(days=settings.REPORT_EXPIRY_DAYS)
        
        old_reports_result = await session.execute(
            select(Report)
            .where(
                and_(
                    Report.created_at < expiry_date,
                    Report.status.in_([
                        ReportStatus.RESOLVED,
                        ReportStatus.CLOSED,
                        ReportStatus.INVALID
                    ])
                )
            )
        )
        
        old_reports = old_reports_result.scalars().all()
        
        for report in old_reports:
            # Archive files to cold storage before deletion
            # Implementation would depend on storage backend
            
            # Mark files for deletion
            await session.execute(
                update(ReportFile)
                .where(ReportFile.report_id == report.id)
                .values(storage_path="archived")
            )
            
            results["files_deleted"] += 1
        
        # Clean old events (keep audit trail for 1 year)
        event_expiry = datetime.now(timezone.utc) - timedelta(days=365)
        
        old_events_result = await session.execute(
            select(Event)
            .where(
                and_(
                    Event.created_at < event_expiry,
                    Event.processed == True
                )
            )
        )
        
        # Delete old processed events
        await session.execute(
            Event.__table__.delete().where(
                and_(
                    Event.created_at < event_expiry,
                    Event.processed == True
                )
            )
        )
        
        # Clean old completed alerts
        alert_expiry = datetime.now(timezone.utc) - timedelta(days=90)
        
        await session.execute(
            Alert.__table__.delete().where(
                and_(
                    Alert.created_at < alert_expiry,
                    Alert.status.in_([
                        AlertStatus.SENT,
                        AlertStatus.DELIVERED,
                        AlertStatus.FAILED
                    ])
                )
            )
        )
        
        await session.commit()
    
    logger.info("Data cleanup completed", results=results)
    return results


@job("maintenance", timeout="20m", connection=redis_queue_sync)
def geocode_organizations_missing_coords(batch_size: int = 200) -> Dict[str, Any]:
    """Geocode organizations that have textual address but missing coordinates."""
    logger.info("Geocoding organizations with missing coordinates", batch_size=batch_size)
    try:
        return asyncio.run(_geocode_orgs_missing_async(batch_size))
    except Exception as e:
        logger.error("Geocode organizations job failed", error=str(e))
        raise


async def _geocode_orgs_missing_async(batch_size: int) -> Dict[str, Any]:
    results = {"processed": 0, "updated": 0, "skipped": 0, "errors": 0}
    async with async_session_maker() as session:
        # Fetch a batch
        result = await session.execute(
            select(Organization)
            .where(
                and_(
                    Organization.address.isnot(None),
                    or_(Organization.latitude.is_(None), Organization.longitude.is_(None))
                )
            )
            .limit(batch_size)
        )
        orgs = result.scalars().all()
        for org in orgs:
            results["processed"] += 1
            try:
                geo = await google_service.geocode(org.address or org.name or "")
                if not geo:
                    results["skipped"] += 1
                    continue
                org.latitude = geo.get("latitude")
                org.longitude = geo.get("longitude")
                # Set PostGIS geometry if available
                if org.latitude and org.longitude:
                    try:
                        org.location = create_point_from_coordinates(org.latitude, org.longitude)
                    except Exception:
                        pass
                results["updated"] += 1
                # Respect rate limits
                await asyncio.sleep(0.1)
            except Exception as e:
                results["errors"] += 1
                logger.warning("Failed to geocode organization", org_id=str(org.id), error=str(e))
        await session.commit()
    logger.info("Geocode organizations completed", results=results)
    return results

@job("maintenance", timeout="10m", connection=redis_queue_sync)
def update_organization_stats() -> Dict[str, int]:
    """Update organization response statistics."""
    logger.info("Updating organization statistics")
    
    try:
        return asyncio.run(_update_organization_stats_async())
    except Exception as e:
        logger.error("Organization stats update failed", error=str(e))
        raise


async def _update_organization_stats_async() -> Dict[str, int]:
    """Async implementation of organization stats update."""
    results = {"organizations_updated": 0}
    
    async with async_session_maker() as session:
        # Get all active organizations
        orgs_result = await session.execute(
            select(Organization).where(Organization.is_active == True)
        )
        
        organizations = orgs_result.scalars().all()
        
        for org in organizations:
            # Calculate average response time
            response_times_result = await session.execute(
                select(Alert.sent_at, Alert.created_at)
                .where(
                    and_(
                        Alert.organization_id == org.id,
                        Alert.status == AlertStatus.SENT,
                        Alert.sent_at.isnot(None),
                        Alert.created_at > datetime.now(timezone.utc) - timedelta(days=30)
                    )
                )
            )
            
            response_times = response_times_result.all()
            
            if response_times:
                total_response_time = sum([
                    (sent - created).total_seconds() / 60  # Convert to minutes
                    for created, sent in response_times
                ])
                avg_response_time = total_response_time / len(response_times)
                org.average_response_time_minutes = avg_response_time
            
            # Count total reports handled
            handled_reports_result = await session.execute(
                select(Report).where(
                    Report.assigned_organization_id == org.id
                )
            )
            
            org.total_reports_handled = len(handled_reports_result.scalars().all())
            
            # Count successful rescues
            successful_reports_result = await session.execute(
                select(Report).where(
                    and_(
                        Report.assigned_organization_id == org.id,
                        Report.status == ReportStatus.RESOLVED
                    )
                )
            )
            
            org.successful_rescues = len(successful_reports_result.scalars().all())
            
            results["organizations_updated"] += 1
        
        await session.commit()
    
    logger.info("Organization stats updated", results=results)
    return results


# =============================================================================
# External API Integration Jobs
# =============================================================================

@job("external", timeout="15m", retry=Retry(max=2, interval=300), connection=redis_queue_sync)
def sync_google_places_data() -> Dict[str, Any]:
    """Synchronize organization data with Google Places API."""
    logger.info("Starting Google Places data sync")
    
    try:
        return asyncio.run(_sync_google_places_data_async())
    except Exception as e:
        logger.error("Google Places sync failed", error=str(e))
        raise


@job("external", timeout="15m", retry=Retry(max=2, interval=300), connection=redis_queue_sync)
def enrich_org_contacts_with_serpapi() -> Dict[str, Any]:
    """Enrich organizations missing contact details using SerpAPI (Google Maps)."""
    logger.info("Starting SerpAPI enrichment job")
    try:
        return asyncio.run(_enrich_org_contacts_with_serpapi_async())
    except Exception as e:
        logger.error("SerpAPI enrichment failed", error=str(e))
        raise


async def _enrich_org_contacts_with_serpapi_async() -> Dict[str, Any]:
    results: Dict[str, Any] = {"processed": 0, "updated": 0, "skipped": 0, "errors": 0}
    async with async_session_maker() as session:
        # Pick candidates with missing phone or website
        result = await session.execute(
            select(Organization).where(
                and_(
                    Organization.is_active == True,
                    or_(Organization.primary_phone.is_(None), Organization.website.is_(None))
                )
            ).limit(500)
        )
        orgs = result.scalars().all()
        for org in orgs:
            results["processed"] += 1
            try:
                # Prefer name + city query
                contact = serpapi_service.get_contact_by_name_city(org.name, org.city)
                if not contact and org.google_place_id:
                    contact = serpapi_service.get_details_by_place_id(org.google_place_id)
                if not contact:
                    results["skipped"] += 1
                    continue
                updated = False
                if contact.get("phone") and not org.primary_phone:
                    org.primary_phone = contact["phone"]
                    updated = True
                if contact.get("website") and not org.website:
                    org.website = contact["website"]
                    updated = True
                if contact.get("place_id") and not org.google_place_id:
                    org.google_place_id = contact["place_id"]
                    updated = True
                if updated:
                    results["updated"] += 1
                await asyncio.sleep(0)
            except Exception as e:
                results["errors"] += 1
                logger.warning("SerpAPI org enrich failed", org_id=str(org.id), error=str(e))
        await session.commit()
    logger.info("SerpAPI enrichment completed", results=results)
    return results


async def _sync_google_places_data_async() -> Dict[str, Any]:
    """Async implementation of Google Places sync."""
    results = {
        "organizations_checked": 0,
        "organizations_updated": 0,
        "new_organizations_found": 0,
        "errors": [],
    }
    
    async with async_session_maker() as session:
        # Get organizations with Google Place IDs
        orgs_result = await session.execute(
            select(Organization).where(
                and_(
                    Organization.google_place_id.isnot(None),
                    Organization.is_active == True
                )
            )
        )
        
        organizations = orgs_result.scalars().all()
        
        for org in organizations:
            try:
                # Get updated place details (כולל טלפון/אתר/סוגים)
                place_details = await google_service.get_place_details(
                    org.google_place_id
                )
                
                if place_details:
                    # Update organization data
                    org.name = place_details.get("name", org.name)
                    # Normalize phone
                    phone = place_details.get("phone") or org.primary_phone
                    if phone:
                        org.primary_phone = _normalize_phone_e164(phone)
                    org.website = place_details.get("website", org.website)
                    org.address = place_details.get("address", org.address)
                    # Normalize opening_hours
                    opening_hours = place_details.get("opening_hours") or place_details.get("hours")
                    if opening_hours:
                        org.operating_hours = opening_hours
                    # specialties מה-"types"
                    types = list(place_details.get("types", []) or [])
                    spec: List[str] = []
                    for t in types:
                        t_low = (t or "").lower()
                        if any(k in t_low for k in ["dog", "cat", "bird", "wild", "reptile", "vet", "shelter", "rescue", "hospital"]):
                            spec.append(t_low)
                    if spec:
                        # מיזוג עם קיימים
                        merged = sorted(list(set((org.specialties or []) + spec)))
                        org.specialties = merged
                    
                    # Update location if needed
                    if place_details.get("latitude"):
                        org.latitude = place_details["latitude"]
                        org.longitude = place_details["longitude"]
                    
                    # עדכון ערוצי התראה לפי פרטי קשר קיימים
                    desired: list[str] = []
                    if org.primary_phone:
                        desired.extend(["whatsapp", "sms"])  # עדיפות ל-WhatsApp
                    if org.email:
                        desired.append("email")
                    if org.telegram_chat_id:
                        desired.append("telegram")
                    if desired:
                        seen = set()
                        org.alert_channels = [c for c in desired if not (c in seen or seen.add(c))]
                    
                    results["organizations_updated"] += 1
                
                results["organizations_checked"] += 1
                
                # Rate limiting
                await asyncio.sleep(0.1)  # Respect Google API rate limits
                
            except Exception as e:
                error_msg = f"Failed to sync {org.name}: {str(e)}"
                results["errors"].append(error_msg)
                logger.warning("Organization sync failed", org_id=str(org.id), error=str(e))
        
        # Search for new veterinary clinics and shelters in configured cities (Redis) or defaults
        try:
            cities_raw = await redis_client.get("import:cities")
            if cities_raw:
                import json as _json
                cities = _json.loads(cities_raw)
            else:
                cities = ["Tel Aviv", "Jerusalem", "Haifa", "Rishon LeZion", "Petah Tikva"]
        except Exception:
            cities = ["Tel Aviv", "Jerusalem", "Haifa", "Rishon LeZion", "Petah Tikva"]
        
        for city in cities:
            try:
                new_places = await google_service.search_veterinary_clinics(city)
                new_shelters = await google_service.search_animal_shelters(city)
                
                for place in (new_places + new_shelters):
                    # Check if organization already exists
                    existing_org = await session.execute(
                        select(Organization).where(
                            Organization.google_place_id == place["place_id"]
                        )
                    )
                    
                    if not existing_org.scalar_one_or_none():
                        # Create new organization with best-effort enrichment
                        raw_phone = place.get("phone") or None
                        norm_phone = _normalize_phone_e164(raw_phone) if raw_phone else None
                        org_type = (
                            OrganizationType.ANIMAL_SHELTER
                            if any(k in (place.get("name") or "").lower() for k in ["shelter", "rescue", "עמותה", "מקלט"]) else
                            OrganizationType.VET_CLINIC
                        )
                        new_org = Organization(
                            name=place["name"],
                            organization_type=org_type,
                            primary_phone=norm_phone,
                            address=place.get("address"),
                            city=city,
                            latitude=place.get("latitude"),
                            longitude=place.get("longitude"),
                            google_place_id=place["place_id"],
                            is_active=True,
                            is_verified=False,
                        )
                        # specialties: מהסוגים של גוגל + סוג ארגון בסיסי
                        types = list(place.get("types", []) or [])
                        specialties: List[str] = []
                        for t in types:
                            t_low = (t or "").lower()
                            if any(k in t_low for k in ["dog", "cat", "bird", "wild", "reptile", "vet", "shelter", "rescue", "hospital"]):
                                specialties.append(t_low)
                        # הוספת קטגוריה נגזרת
                        if org_type == OrganizationType.VET_CLINIC:
                            specialties.append("veterinary")
                        if org_type == OrganizationType.ANIMAL_SHELTER:
                            specialties.append("shelter")
                        # ייחודיות
                        if specialties:
                            new_org.specialties = sorted(list(set(specialties)))
                        # ערוצי התרעה לפי פרטים שיש
                        channels: List[str] = []
                        if norm_phone:
                            channels.extend(["whatsapp", "sms"])
                        if place.get("website"):
                            # אין לנו מייל בשלב החיפוש, נשאיר לאימות/SerpAPI
                            pass
                        # תמיד נוסיף טלגרם רק אם קיים chat id (לא קיים פה)
                        if channels:
                            # ייחודיות תוך שמירה על סדר
                            seen = set()
                            new_org.alert_channels = [c for c in channels if not (c in seen or seen.add(c))]

                        session.add(new_org)
                        results["new_organizations_found"] += 1
                
                # Rate limiting
                await asyncio.sleep(1)  # Longer delay for searches
                
            except Exception as e:
                error_msg = f"Failed to search {city}: {str(e)}"
                results["errors"].append(error_msg)
        
        await session.commit()
    
    logger.info("Google Places sync completed", results=results)
    return results


# =============================================================================
# Testing and Development Jobs
# =============================================================================

@job("default", timeout="1m", connection=redis_queue_sync)
def send_test_alert(message: str = "Test alert from Animal Rescue Bot") -> Dict[str, str]:
    """Send a test alert for development and monitoring."""
    logger.info("Sending test alert", message=message)
    
    # This would send to a test channel/email
    # Implementation depends on configured test recipients
    
    return {
        "status": "success",
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@job("maintenance", timeout="5m", connection=redis_queue_sync)
def generate_daily_statistics() -> Dict[str, Any]:
    """Generate daily statistics for monitoring and reporting."""
    logger.info("Generating daily statistics")
    
    try:
        return asyncio.run(_generate_daily_statistics_async())
    except Exception as e:
        logger.error("Statistics generation failed", error=str(e))
        raise


async def _generate_daily_statistics_async() -> Dict[str, Any]:
    """Async implementation of statistics generation."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    
    stats = {
        "date": today.isoformat(),
        "reports": {},
        "alerts": {},
        "organizations": {},
        "users": {},
    }
    
    async with async_session_maker() as session:
        # Report statistics
        reports_today = await session.execute(
            select(Report).where(
                Report.created_at >= datetime.combine(yesterday, datetime.min.time().replace(tzinfo=timezone.utc))
            )
        )
        
        reports = reports_today.scalars().all()
        
        stats["reports"] = {
            "total": len(reports),
            "by_urgency": {},
            "by_animal_type": {},
            "by_status": {},
        }
        
        for report in reports:
            # Count by urgency
            urgency = report.urgency_level.value
            stats["reports"]["by_urgency"][urgency] = stats["reports"]["by_urgency"].get(urgency, 0) + 1
            
            # Count by animal type
            animal = report.animal_type.value
            stats["reports"]["by_animal_type"][animal] = stats["reports"]["by_animal_type"].get(animal, 0) + 1
            
            # Count by status
            status = report.status.value
            stats["reports"]["by_status"][status] = stats["reports"]["by_status"].get(status, 0) + 1
        
        # Alert statistics
        alerts_today = await session.execute(
            select(Alert).where(
                Alert.created_at >= datetime.combine(yesterday, datetime.min.time().replace(tzinfo=timezone.utc))
            )
        )
        
        alerts = alerts_today.scalars().all()
        
        stats["alerts"] = {
            "total": len(alerts),
            "by_channel": {},
            "by_status": {},
        }
        
        for alert in alerts:
            channel = alert.channel.value
            stats["alerts"]["by_channel"][channel] = stats["alerts"]["by_channel"].get(channel, 0) + 1
            
            status = alert.status.value
            stats["alerts"]["by_status"][status] = stats["alerts"]["by_status"].get(status, 0) + 1
        
        # Organization statistics
        active_orgs = await session.execute(
            select(Organization).where(Organization.is_active == True)
        )
        
        stats["organizations"]["active_count"] = len(active_orgs.scalars().all())
        
        # User statistics
        active_users = await session.execute(
            select(User).where(User.is_active == True)
        )
        
        stats["users"]["active_count"] = len(active_users.scalars().all())
    
    # Store statistics in Redis for quick access
    await redis_client.setex(
        f"daily_stats:{today.isoformat()}",
        86400,  # 24 hours
        json.dumps(stats, default=str)
    )
    
    logger.info("Daily statistics generated", stats=stats)
    return stats


# =============================================================================
# Job Scheduling and Queue Management
# =============================================================================

def enqueue_or_run(func, *args, **kwargs):
    """Enqueue an RQ job when workers enabled, otherwise run inline (async if available)."""
    if settings.ENABLE_WORKERS:
        return func.delay(*args, **kwargs)
    # Inline mode
    # If there is an async implementation helper, prefer it
    name = getattr(func, "__name__", "")
    if name == "process_new_report":
        # process_new_report has async impl _process_new_report_async
        return asyncio.create_task(_process_new_report_async(*args, **kwargs))
    if name == "send_organization_alert":
        return asyncio.create_task(_send_organization_alert_async(*args, **kwargs))
    if name == "retry_failed_alerts":
        return asyncio.create_task(_retry_failed_alerts_async())
    if name == "cleanup_old_data":
        return asyncio.create_task(_cleanup_old_data_async())
    if name == "update_organization_stats":
        return asyncio.create_task(_update_organization_stats_async())
    if name == "sync_google_places_data":
        return asyncio.create_task(_sync_google_places_data_async())
    if name == "generate_daily_statistics":
        return asyncio.create_task(_generate_daily_statistics_async())
    # Fallback: run sync function inline
    return func(*args, **kwargs)

def schedule_recurring_jobs():
    """Schedule recurring background jobs."""
    from rq_scheduler import Scheduler
    from datetime import time
    
    scheduler = Scheduler(connection=redis_queue_sync)
    
    # Daily cleanup at 2 AM
    scheduler.cron(
        cron_string="0 2 * * *",  # Every day at 2 AM
        func=cleanup_old_data,
        timeout="30m",
        use_local_timezone=False
    )
    
    # Update organization stats every 6 hours
    scheduler.cron(
        cron_string="0 */6 * * *",  # Every 6 hours
        func=update_organization_stats,
        timeout="10m",
        use_local_timezone=False
    )
    
    # Sync Google Places data weekly
    scheduler.cron(
        cron_string="0 3 * * 0",  # Every Sunday at 3 AM
        func=sync_google_places_data,
        timeout="15m",
        use_local_timezone=False
    )
    
    # SerpAPI enrichment daily at 03:30
    scheduler.cron(
        cron_string="30 3 * * *",  # Every day at 03:30
        func=enrich_org_contacts_with_serpapi,
        timeout="15m",
        use_local_timezone=False
    )
    
    # Generate daily statistics at midnight
    scheduler.cron(
        cron_string="0 0 * * *",  # Every day at midnight
        func=generate_daily_statistics,
        timeout="5m",
        use_local_timezone=False
    )
    
    # Retry failed alerts every 15 minutes
    scheduler.cron(
        cron_string="*/15 * * * *",  # Every 15 minutes
        func=retry_failed_alerts,
        timeout="2m",
        use_local_timezone=False
    )
    
    # Reconcile alert channels (configurable via RECONCILE_ALERT_CHANNELS_CRON, default hourly)
    try:
        from app.workers.jobs import reconcile_alert_channels  # type: ignore
        cron_expr = os.getenv("RECONCILE_ALERT_CHANNELS_CRON", "0 * * * *")
        scheduler.cron(
            cron_string=cron_expr,
            func=reconcile_alert_channels,
            timeout="5m",
            use_local_timezone=False
        )
    except Exception:
        # In case function not yet imported in certain builds, skip scheduling
        pass
    
    logger.info("Recurring jobs scheduled")


# =============================================================================
# Export Public Interface
# =============================================================================

__all__ = [
    "process_new_report",
    "send_organization_alert",
    "retry_failed_alerts",
    "cleanup_old_data",
    "update_organization_stats",
    "sync_google_places_data",
    "enrich_org_contacts_with_serpapi",
    "send_test_alert",
    "generate_daily_statistics",
    "schedule_recurring_jobs",
    "geocode_organizations_missing_coords",
]
