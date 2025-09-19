"""
Email service for the Animal Rescue Bot system.

Handles sending various types of emails including:
- Alert notifications to organizations
- Status updates to reporters  
- Administrative notifications
- Bulk communications
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
import asyncio
from concurrent.futures import ThreadPoolExecutor
import aiofiles
import jinja2

import structlog
from app.core.config import settings
from app.core.exceptions import (
    AnimalRescueException,
    ConfigurationError,
    ExternalServiceError
)
from app.core.cache import redis_client
from app.core.i18n import get_text, detect_language

logger = structlog.get_logger(__name__)

# Email configuration validation / discoverability
# אם SMTP לא מוגדר – נרשום שהשירות מושבת (לא אזהרה מבלבלת)
if not all([settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER]):
    logger.info("Email service disabled (SMTP not configured)")


@dataclass
class EmailAddress:
    """Represents an email address with optional display name."""
    email: str
    name: Optional[str] = None
    
    def __str__(self) -> str:
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Represents an email message to be sent."""
    to: List[EmailAddress]
    subject: str
    body_text: str
    body_html: Optional[str] = None
    from_addr: Optional[EmailAddress] = None
    cc: Optional[List[EmailAddress]] = None
    bcc: Optional[List[EmailAddress]] = None
    attachments: Optional[List[EmailAttachment]] = None
    reply_to: Optional[EmailAddress] = None
    headers: Optional[Dict[str, str]] = None
    priority: str = "normal"  # low, normal, high
    
    def __post_init__(self):
        if not self.from_addr:
            self.from_addr = EmailAddress(
                email=settings.EMAILS_FROM_EMAIL,
                name=settings.EMAILS_FROM_NAME
            )


class EmailTemplateEngine:
    """Handles email template rendering with Jinja2."""
    
    def __init__(self, templates_dir: str = "app/templates/emails"):
        self.templates_dir = Path(templates_dir)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize Jinja2 environment
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.templates_dir)),
            autoescape=jinja2.select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.env.filters['format_datetime'] = self._format_datetime_filter
        self.env.filters['translate'] = self._translate_filter
    
    def _format_datetime_filter(self, dt, format_string='%Y-%m-%d %H:%M'):
        """Jinja2 filter for datetime formatting."""
        if dt is None:
            return ""
        return dt.strftime(format_string)
    
    def _translate_filter(self, key, language='en', **kwargs):
        """Jinja2 filter for translations."""
        return get_text(key, language, **kwargs)
    
    def render_template(
        self,
        template_name: str,
        context: Dict[str, Any],
        language: str = "en"
    ) -> tuple[str, str]:
        """
        Render email template to text and HTML.
        
        Returns:
            tuple of (text_body, html_body)
        """
        # Add language and common context
        context.update({
            'language': language,
            'app_name': settings.APP_NAME,
            'support_email': settings.EMAILS_FROM_EMAIL,
            'base_url': getattr(settings, 'BASE_URL', 'https://localhost:8000')
        })
        
        try:
            # Try to render HTML template
            html_template = self.env.get_template(f"{template_name}.html")
            html_body = html_template.render(**context)
        except jinja2.TemplateNotFound:
            logger.warning(f"HTML template not found: {template_name}.html")
            html_body = None
        
        try:
            # Try to render text template
            text_template = self.env.get_template(f"{template_name}.txt")
            text_body = text_template.render(**context)
        except jinja2.TemplateNotFound:
            # Fallback: strip HTML if we have HTML template
            if html_body:
                import re
                text_body = re.sub('<[^<]+?>', '', html_body)
                text_body = re.sub(r'\s+', ' ', text_body).strip()
            else:
                logger.error(f"No templates found for: {template_name}")
                raise AnimalRescueException(f"Email template not found: {template_name}")
        
        return text_body, html_body


class EmailService:
    """Main email service for sending emails."""
    
    def __init__(self):
        self.template_engine = EmailTemplateEngine()
        self.executor = ThreadPoolExecutor(max_workers=3)
        self._smtp_pool: Dict[str, smtplib.SMTP] = {}
        
        # Email sending statistics
        self.stats = {
            'sent': 0,
            'failed': 0,
            'queued': 0
        }
    
    def _get_smtp_connection(self) -> smtplib.SMTP:
        """Get or create SMTP connection."""
        if not all([settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER]):
            raise ConfigurationError(
                "SMTP_HOST",
                "Email service not configured properly"
            )
        
        try:
            # Create connection
            if settings.SMTP_TLS:
                context = ssl.create_default_context()
                smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
                smtp.starttls(context=context)
            else:
                smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
            
            # Authenticate
            if settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            
            return smtp
            
        except Exception as e:
            logger.error("Failed to create SMTP connection", error=str(e))
            raise ExternalServiceError(
                service_name="SMTP Server",
                message=f"Connection failed: {str(e)}"
            )
    
    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build MIME message from EmailMessage."""
        # Create base message
        msg = MIMEMultipart('alternative')
        
        # Headers
        msg['From'] = str(message.from_addr)
        msg['To'] = ', '.join(str(addr) for addr in message.to)
        msg['Subject'] = message.subject
        
        if message.cc:
            msg['Cc'] = ', '.join(str(addr) for addr in message.cc)
        
        if message.reply_to:
            msg['Reply-To'] = str(message.reply_to)
        
        # Priority headers
        if message.priority == "high":
            msg['X-Priority'] = '1'
            msg['X-MSMail-Priority'] = 'High'
            msg['Importance'] = 'High'
        elif message.priority == "low":
            msg['X-Priority'] = '5'
            msg['X-MSMail-Priority'] = 'Low'
            msg['Importance'] = 'Low'
        
        # Custom headers
        if message.headers:
            for key, value in message.headers.items():
                msg[key] = value
        
        # Add text body
        text_part = MIMEText(message.body_text, 'plain', 'utf-8')
        msg.attach(text_part)
        
        # Add HTML body if provided
        if message.body_html:
            html_part = MIMEText(message.body_html, 'html', 'utf-8')
            msg.attach(html_part)
        
        # Add attachments
        if message.attachments:
            for attachment in message.attachments:
                part = MIMEBase(*attachment.mime_type.split('/'))
                part.set_payload(attachment.content)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {attachment.filename}'
                )
                msg.attach(part)
        
        return msg
    
    def _send_email_sync(self, message: EmailMessage) -> bool:
        """Send email synchronously."""
        try:
            smtp = self._get_smtp_connection()
            mime_msg = self._build_mime_message(message)
            
            # Collect all recipients
            recipients = [addr.email for addr in message.to]
            if message.cc:
                recipients.extend(addr.email for addr in message.cc)
            if message.bcc:
                recipients.extend(addr.email for addr in message.bcc)
            
            # Send email
            smtp.send_message(mime_msg, to_addrs=recipients)
            smtp.quit()
            
            logger.info(
                "Email sent successfully",
                to=recipients,
                subject=message.subject
            )
            
            self.stats['sent'] += 1
            return True
            
        except Exception as e:
            logger.error(
                "Failed to send email",
                error=str(e),
                to=[addr.email for addr in message.to],
                subject=message.subject
            )
            self.stats['failed'] += 1
            return False
    
    async def send_email(self, message: EmailMessage) -> bool:
        """Send email asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._send_email_sync,
            message
        )
    
    async def send_template_email(
        self,
        template_name: str,
        to_addresses: List[Union[str, EmailAddress]], 
        context: Dict[str, Any],
        subject: Optional[str] = None,
        language: str = "en",
        **kwargs
    ) -> bool:
        """Send email using template."""
        # Convert string addresses to EmailAddress objects
        to_addrs = []
        for addr in to_addresses:
            if isinstance(addr, str):
                to_addrs.append(EmailAddress(email=addr))
            else:
                to_addrs.append(addr)
        
        # Render template
        try:
            text_body, html_body = self.template_engine.render_template(
                template_name, context, language
            )
        except Exception as e:
            logger.error(
                "Failed to render email template",
                template=template_name,
                error=str(e)
            )
            return False
        
        # Use subject from context if not provided
        if not subject:
            subject = context.get('subject', f'Notification from {settings.APP_NAME}')
        
        # Create message
        message = EmailMessage(
            to=to_addrs,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            **kwargs
        )
        
        return await self.send_email(message)
    
    async def send_alert_email(
        self,
        organization_email: str,
        report_data: Dict[str, Any],
        language: str = "en"
    ) -> bool:
        """Send alert email to organization about new report."""
        context = {
            'report': report_data,
            'organization_name': report_data.get('organization_name', 'Organization'),
            'urgent': report_data.get('urgency_level') == 'critical',
            'subject': get_text('alert.new_report.subject', language)
        }
        
        return await self.send_template_email(
            template_name="new_report_alert",
            to_addresses=[organization_email],
            context=context,
            subject=context['subject'],
            language=language,
            priority="high" if context['urgent'] else "normal"
        )
    
    async def send_status_update_email(
        self,
        reporter_email: str,
        report_data: Dict[str, Any],
        old_status: str,
        new_status: str,
        language: str = "en"
    ) -> bool:
        """Send status update email to report submitter."""
        context = {
            'report': report_data,
            'old_status': old_status,
            'new_status': new_status,
            'reporter_name': report_data.get('reporter_name', 'Reporter'),
            'subject': get_text('alert.status_update.subject', language, 
                              status=new_status)
        }
        
        return await self.send_template_email(
            template_name="status_update",
            to_addresses=[reporter_email],
            context=context,
            subject=context['subject'],
            language=language
        )
    
    async def send_bulk_email(
        self,
        template_name: str,
        recipients: List[Dict[str, Any]],
        common_context: Dict[str, Any],
        batch_size: int = 10
    ) -> Dict[str, int]:
        """Send bulk emails with personalized content."""
        results = {"sent": 0, "failed": 0}
        
        # Process in batches to avoid overwhelming SMTP server
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            tasks = []
            
            for recipient in batch:
                # Merge common context with personal context
                context = {**common_context, **recipient.get('context', {})}
                language = recipient.get('language', 'en')
                
                # Detect language from email if not specified
                if 'language' not in recipient:
                    if 'name' in recipient:
                        language = detect_language(recipient['name'])
                
                task = self.send_template_email(
                    template_name=template_name,
                    to_addresses=[recipient['email']],
                    context=context,
                    language=language
                )
                tasks.append(task)
            
            # Execute batch
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    results["failed"] += 1
                    logger.error("Bulk email failed", error=str(result))
                elif result:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
            
            # Small delay between batches
            if i + batch_size < len(recipients):
                await asyncio.sleep(1)
        
        logger.info("Bulk email completed", **results, total=len(recipients))
        return results
    
    async def test_email_connection(self) -> Dict[str, Any]:
        """Test email service configuration."""
        # אם SMTP לא מוגדר – נחזיר סטטוס מושבת בצורה ברורה
        if not all([settings.SMTP_HOST, settings.SMTP_PORT, settings.SMTP_USER]):
            return {
                "status": "disabled",
                "reason": "SMTP not configured",
                "smtp_host": settings.SMTP_HOST,
                "smtp_port": settings.SMTP_PORT,
            }
        try:
            smtp = self._get_smtp_connection()
            smtp.noop()  # Test connection
            smtp.quit()
            
            return {
                "status": "healthy",
                "smtp_host": settings.SMTP_HOST,
                "smtp_port": settings.SMTP_PORT,
                "smtp_user": settings.SMTP_USER,
                "smtp_tls": settings.SMTP_TLS
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "smtp_host": settings.SMTP_HOST,
                "smtp_port": settings.SMTP_PORT
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get email service statistics."""
        return {
            "emails_sent": self.stats['sent'],
            "emails_failed": self.stats['failed'], 
            "emails_queued": self.stats['queued'],
            "success_rate": (
                self.stats['sent'] / (self.stats['sent'] + self.stats['failed'])
                if (self.stats['sent'] + self.stats['failed']) > 0 else 0
            )
        }
    
    async def close(self):
        """Clean up resources."""
        self.executor.shutdown(wait=True)
        for smtp in self._smtp_pool.values():
            try:
                smtp.quit()
            except:
                pass
        self._smtp_pool.clear()


# Global email service instance
email_service = EmailService()


# Convenience functions for common operations
async def send_email(
    to_addresses: List[str],
    subject: str,
    body: str,
    body_html: Optional[str] = None,
    **kwargs
) -> bool:
    """Send simple email."""
    to_addrs = [EmailAddress(email=addr) for addr in to_addresses]
    message = EmailMessage(
        to=to_addrs,
        subject=subject,
        body_text=body,
        body_html=body_html,
        **kwargs
    )
    return await email_service.send_email(message)


async def send_alert_notification(
    organization_email: str,
    report_data: Dict[str, Any],
    language: str = "en"
) -> bool:
    """Send alert notification to organization."""
    return await email_service.send_alert_email(
        organization_email, report_data, language
    )


async def send_status_notification(
    reporter_email: str,
    report_data: Dict[str, Any],
    old_status: str,
    new_status: str,
    language: str = "en"
) -> bool:
    """Send status update notification."""
    return await email_service.send_status_update_email(
        reporter_email, report_data, old_status, new_status, language
    )


async def test_email_service() -> Dict[str, Any]:
    """Test email service health."""
    return await email_service.test_email_connection()


# Cleanup on module unload
import atexit


def _close_email_service_on_exit():
    """Close EmailService safely at interpreter exit.
    Avoid using create_task when no running loop exists.
    """
    try:
        loop = asyncio.get_running_loop()
        if getattr(loop, "is_running", lambda: False)():
            try:
                loop.create_task(email_service.close())
            except Exception:
                pass
        else:
            try:
                asyncio.run(email_service.close())
            except Exception:
                pass
    except RuntimeError:
        # No running loop
        try:
            asyncio.run(email_service.close())
        except Exception:
            pass


atexit.register(_close_email_service_on_exit)
