"""
Telegram alerts service for the Animal Rescue Bot system.

Handles sending alert messages via Telegram to organizations and administrators.
Supports rich formatting, inline keyboards, and message templates.
"""

import asyncio
import json
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, asdict
from urllib.parse import urlencode
from enum import Enum

import httpx
import structlog
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest, Forbidden, NetworkError

from app.core.config import settings
from app.core.cache import redis_client, CacheManager
from app.core.exceptions import (
    TelegramAPIError,
    ExternalServiceError,
    ConfigurationError,
    RateLimitExceededError
)
from app.core.i18n import get_text, detect_language, get_text_direction

logger = structlog.get_logger(__name__)

# Constants
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
RETRY_DELAYS = [1, 3, 5, 10, 30]  # seconds
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MESSAGES = 30  # messages per window


class MessageType(Enum):
    """Types of Telegram messages."""
    TEXT = "text"
    PHOTO = "photo"
    DOCUMENT = "document"
    LOCATION = "location"
    INLINE_QUERY = "inline_query"


class AlertPriority(Enum):
    """Alert priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TelegramButton:
    """Represents an inline keyboard button."""
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None
    switch_inline_query: Optional[str] = None


@dataclass
class TelegramMessage:
    """Represents a Telegram message to be sent."""
    chat_id: Union[str, int]
    text: str
    parse_mode: str = ParseMode.HTML
    disable_web_page_preview: bool = False
    disable_notification: bool = False
    reply_markup: Optional[List[List[TelegramButton]]] = None
    message_type: MessageType = MessageType.TEXT
    file_path: Optional[str] = None
    caption: Optional[str] = None
    
    def __post_init__(self):
        # Truncate message if too long
        if self.text and len(self.text) > MAX_MESSAGE_LENGTH:
            self.text = self.text[:MAX_MESSAGE_LENGTH-10] + "...(מקוצר)"
        
        if self.caption and len(self.caption) > MAX_CAPTION_LENGTH:
            self.caption = self.caption[:MAX_CAPTION_LENGTH-10] + "...(מקוצר)"


class TelegramFormatter:
    """Formats messages for Telegram with proper escaping and styling."""
    
    @staticmethod
    def escape_html(text: str) -> str:
        """Escape HTML special characters for Telegram."""
        if not text:
            return ""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    
    @staticmethod
    def bold(text: str) -> str:
        """Make text bold."""
        return f"<b>{TelegramFormatter.escape_html(text)}</b>"
    
    @staticmethod
    def italic(text: str) -> str:
        """Make text italic."""
        return f"<i>{TelegramFormatter.escape_html(text)}</i>"
    
    @staticmethod
    def code(text: str) -> str:
        """Format as code."""
        return f"<code>{TelegramFormatter.escape_html(text)}</code>"
    
    @staticmethod
    def link(text: str, url: str) -> str:
        """Create a link."""
        return f'<a href="{url}">{TelegramFormatter.escape_html(text)}</a>'
    
    @staticmethod
    def format_report_alert(report_data: Dict[str, Any], language: str = "he") -> str:
        """Format a new report alert message."""
        fmt = TelegramFormatter
        
        # RTL/LTR handling
        direction = get_text_direction(language)
        
        # Build message
        lines = []
        
        # Header
        if report_data.get('urgency_level') == 'critical':
            lines.append(fmt.bold("🚨 " + get_text('alert.urgent_report', language)))
        else:
            lines.append(fmt.bold("🐕 " + get_text('alert.new_report', language)))
        
        lines.append("")
        
        # Report details
        if report_data.get('animal_type'):
            animal_type = get_text(f'animal.{report_data["animal_type"]}', language)
            lines.append(f"🐾 {fmt.bold(get_text('report.animal_type', language))}: {animal_type}")
        
        if report_data.get('urgency_level'):
            urgency = get_text(f'urgency.{report_data["urgency_level"]}', language)
            urgency_icon = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(
                report_data["urgency_level"], "⚪"
            )
            lines.append(f"{urgency_icon} {fmt.bold(get_text('report.urgency', language))}: {urgency}")
        
        # Location
        if report_data.get('address'):
            lines.append(f"📍 {fmt.bold(get_text('report.location', language))}: {fmt.escape_html(report_data['address'])}")
        elif report_data.get('latitude') and report_data.get('longitude'):
            lines.append(f"📍 {fmt.bold(get_text('report.coordinates', language))}: {report_data['latitude']:.4f}, {report_data['longitude']:.4f}")
        
        # Description
        if report_data.get('description'):
            description = report_data['description'][:200]
            if len(report_data['description']) > 200:
                description += "..."
            lines.append(f"📝 {fmt.bold(get_text('report.description', language))}: {fmt.italic(description)}")
        
        lines.append("")
        
        # Reporter info
        if report_data.get('reporter_name'):
            lines.append(f"👤 {fmt.bold(get_text('report.reporter', language))}: {fmt.escape_html(report_data['reporter_name'])}")
        
        # Report ID
        if report_data.get('public_id'):
            lines.append(f"🆔 {fmt.bold(get_text('report.id', language))}: {fmt.code(report_data['public_id'])}")
        
        # Timestamps
        if report_data.get('created_at'):
            created_at = report_data['created_at'].strftime('%d/%m/%Y %H:%M')
            lines.append(f"⏰ {fmt.bold(get_text('report.created_at', language))}: {created_at}")
        
        message = "\n".join(lines)
        
        # Add direction marker for RTL languages
        if direction == "rtl":
            message = "\u202E" + message  # Right-to-left override
        
        return message
    
    @staticmethod
    def format_status_update(
        report_data: Dict[str, Any], 
        old_status: str, 
        new_status: str,
        language: str = "he"
    ) -> str:
        """Format a status update message."""
        fmt = TelegramFormatter
        
        lines = []
        lines.append(fmt.bold("📱 " + get_text('alert.status_update.title', language)))
        lines.append("")
        
        # Report info
        if report_data.get('public_id'):
            lines.append(f"🆔 {fmt.bold(get_text('report.id', language))}: {fmt.code(report_data['public_id'])}")
        
        # Status change
        old_status_text = get_text(f'status.{old_status}', language)
        new_status_text = get_text(f'status.{new_status}', language)
        
        status_icons = {
            'submitted': '📝',
            'acknowledged': '👀',
            'in_progress': '🚑',
            'resolved': '✅',
            'closed': '🔒'
        }
        
        old_icon = status_icons.get(old_status, '⚪')
        new_icon = status_icons.get(new_status, '⚪')
        
        lines.append(f"📊 {fmt.bold(get_text('report.status_change', language))}:")
        lines.append(f"   {old_icon} {old_status_text} ➡️ {new_icon} {new_status_text}")
        
        lines.append("")
        
        # Additional info based on status
        if new_status == 'resolved':
            lines.append(fmt.italic("🎉 " + get_text('status.resolved_message', language)))
        elif new_status == 'in_progress':
            lines.append(fmt.italic("🚑 " + get_text('status.in_progress_message', language)))
        
        return "\n".join(lines)


class TelegramRateLimiter:
    """Rate limiter for Telegram API calls."""
    
    def __init__(self):
        self.cache = CacheManager()
    
    async def check_rate_limit(self, chat_id: Union[str, int]) -> bool:
        """Check if rate limit allows sending message."""
        key = f"telegram_rate_limit:{chat_id}"
        
        # Get current count
        current = await self.cache.get(key)
        if current is None:
            current = 0
        else:
            current = int(current)
        
        if current >= RATE_LIMIT_MESSAGES:
            logger.warning(
                "Telegram rate limit exceeded",
                chat_id=chat_id,
                current_count=current,
                limit=RATE_LIMIT_MESSAGES
            )
            return False
        
        # Increment counter
        await self.cache.set(key, current + 1, ttl=RATE_LIMIT_WINDOW)
        return True
    
    async def reset_rate_limit(self, chat_id: Union[str, int]):
        """Reset rate limit for chat."""
        key = f"telegram_rate_limit:{chat_id}"
        await self.cache.delete(key)


class TelegramAlertsService:
    """Main service for sending Telegram alerts."""
    
    def __init__(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise ConfigurationError(
                "TELEGRAM_BOT_TOKEN",
                "Telegram bot token is required for alerts service"
            )
        
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        self.rate_limiter = TelegramRateLimiter()
        self.formatter = TelegramFormatter()
        
        # Statistics
        self.stats = {
            'sent': 0,
            'failed': 0,
            'rate_limited': 0
        }
    
    async def _create_inline_keyboard(
        self, 
        buttons: List[List[TelegramButton]]
    ) -> InlineKeyboardMarkup:
        """Create inline keyboard from button data."""
        keyboard = []
        
        for button_row in buttons:
            row = []
            for button in button_row:
                if button.callback_data:
                    btn = InlineKeyboardButton(
                        text=button.text,
                        callback_data=button.callback_data
                    )
                elif button.url:
                    btn = InlineKeyboardButton(
                        text=button.text,
                        url=button.url
                    )
                elif button.switch_inline_query:
                    btn = InlineKeyboardButton(
                        text=button.text,
                        switch_inline_query=button.switch_inline_query
                    )
                else:
                    continue
                
                row.append(btn)
            
            if row:
                keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)
    
    async def send_message(
        self,
        message: TelegramMessage,
        retry_count: int = 0
    ) -> bool:
        """Send a Telegram message with retry logic."""
        
        # Check rate limit
        if not await self.rate_limiter.check_rate_limit(message.chat_id):
            self.stats['rate_limited'] += 1
            raise RateLimitExceededError(
                "Telegram rate limit exceeded for chat",
                retry_after=RATE_LIMIT_WINDOW
            )
        
        try:
            # Prepare reply markup
            reply_markup = None
            if message.reply_markup:
                reply_markup = await self._create_inline_keyboard(message.reply_markup)
            
            # Send based on message type
            if message.message_type == MessageType.TEXT:
                await self.bot.send_message(
                    chat_id=message.chat_id,
                    text=message.text,
                    parse_mode=message.parse_mode,
                    disable_web_page_preview=message.disable_web_page_preview,
                    disable_notification=message.disable_notification,
                    reply_markup=reply_markup
                )
            
            elif message.message_type == MessageType.PHOTO and message.file_path:
                with open(message.file_path, 'rb') as photo:
                    await self.bot.send_photo(
                        chat_id=message.chat_id,
                        photo=photo,
                        caption=message.caption or message.text,
                        parse_mode=message.parse_mode,
                        disable_notification=message.disable_notification,
                        reply_markup=reply_markup
                    )
            
            elif message.message_type == MessageType.LOCATION:
                # Extract coordinates from message or use provided data
                latitude = getattr(message, 'latitude', 0)
                longitude = getattr(message, 'longitude', 0)
                
                await self.bot.send_location(
                    chat_id=message.chat_id,
                    latitude=latitude,
                    longitude=longitude,
                    disable_notification=message.disable_notification,
                    reply_markup=reply_markup
                )
            
            logger.info(
                "Telegram message sent successfully",
                chat_id=message.chat_id,
                message_type=message.message_type.value
            )
            
            self.stats['sent'] += 1
            return True
            
        except Forbidden:
            logger.error(
                "Bot blocked by user",
                chat_id=message.chat_id
            )
            self.stats['failed'] += 1
            return False
            
        except BadRequest as e:
            logger.error(
                "Invalid request to Telegram API",
                chat_id=message.chat_id,
                error=str(e)
            )
            self.stats['failed'] += 1
            return False
            
        except NetworkError as e:
            # Retry on network errors
            if retry_count < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[retry_count]
                logger.warning(
                    "Telegram network error, retrying",
                    chat_id=message.chat_id,
                    retry_count=retry_count,
                    delay=delay,
                    error=str(e)
                )
                await asyncio.sleep(delay)
                return await self.send_message(message, retry_count + 1)
            
            logger.error(
                "Telegram network error, max retries exceeded",
                chat_id=message.chat_id,
                error=str(e)
            )
            self.stats['failed'] += 1
            return False
            
        except TelegramError as e:
            # Handle other Telegram errors
            if "Too Many Requests" in str(e):
                # Extract retry_after from error if available
                retry_after = 60  # default
                self.stats['rate_limited'] += 1
                raise RateLimitExceededError(
                    "Telegram API rate limit exceeded",
                    retry_after=retry_after
                )
            
            logger.error(
                "Telegram API error",
                chat_id=message.chat_id,
                error=str(e)
            )
            self.stats['failed'] += 1
            return False
        
        except Exception as e:
            logger.error(
                "Unexpected error sending Telegram message",
                chat_id=message.chat_id,
                error=str(e),
                error_type=type(e).__name__
            )
            self.stats['failed'] += 1
            return False
    
    async def send_report_alert(
        self,
        chat_id: Union[str, int],
        report_data: Dict[str, Any],
        language: str = "he"
    ) -> bool:
        """Send new report alert to organization."""
        
        # Format message
        text = self.formatter.format_report_alert(report_data, language)
        
        # Create action buttons
        buttons = []
        if report_data.get('public_id'):
            view_url = f"{getattr(settings, 'BASE_URL', 'https://localhost:8000')}/reports/{report_data['public_id']}"
            buttons.append([
                TelegramButton(
                    text=get_text('button.view_report', language),
                    url=view_url
                )
            ])
        
        # Add quick action buttons for organizations
        action_row = [
            TelegramButton(
                text=get_text('button.acknowledge', language),
                callback_data=f"ack_{report_data.get('id', '')}"
            ),
            TelegramButton(
                text=get_text('button.assign_to_me', language),
                callback_data=f"assign_{report_data.get('id', '')}"
            )
        ]
        buttons.append(action_row)
        
        message = TelegramMessage(
            chat_id=chat_id,
            text=text,
            reply_markup=buttons,
            disable_notification=(report_data.get('urgency_level') != 'critical')
        )
        
        return await self.send_message(message)
    
    async def send_status_update_alert(
        self,
        chat_id: Union[str, int],
        report_data: Dict[str, Any],
        old_status: str,
        new_status: str,
        language: str = "he"
    ) -> bool:
        """Send status update alert."""
        
        text = self.formatter.format_status_update(
            report_data, old_status, new_status, language
        )
        
        # Add view button
        buttons = []
        if report_data.get('public_id'):
            view_url = f"{getattr(settings, 'BASE_URL', 'https://localhost:8000')}/reports/{report_data['public_id']}"
            buttons.append([
                TelegramButton(
                    text=get_text('button.view_details', language),
                    url=view_url
                )
            ])
        
        message = TelegramMessage(
            chat_id=chat_id,
            text=text,
            reply_markup=buttons if buttons else None
        )
        
        return await self.send_message(message)
    
    async def send_bulk_alert(
        self,
        chat_ids: List[Union[str, int]],
        message_text: str,
        buttons: Optional[List[List[TelegramButton]]] = None,
        language: str = "he"
    ) -> Dict[str, int]:
        """Send alert to multiple chats."""
        results = {"sent": 0, "failed": 0, "rate_limited": 0}
        
        tasks = []
        for chat_id in chat_ids:
            message = TelegramMessage(
                chat_id=chat_id,
                text=message_text,
                reply_markup=buttons
            )
            tasks.append(self.send_message(message))
        
        # Execute with some concurrency limit
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
        
        async def send_with_semaphore(msg):
            async with semaphore:
                return await self.send_message(msg)
        
        batch_results = await asyncio.gather(
            *[send_with_semaphore(
                TelegramMessage(chat_id=cid, text=message_text, reply_markup=buttons)
            ) for cid in chat_ids],
            return_exceptions=True
        )
        
        for result in batch_results:
            if isinstance(result, RateLimitExceededError):
                results["rate_limited"] += 1
            elif isinstance(result, Exception):
                results["failed"] += 1
            elif result:
                results["sent"] += 1
            else:
                results["failed"] += 1
        
        logger.info("Bulk Telegram alert completed", **results, total=len(chat_ids))
        return results
    
    async def send_test_message(self, chat_id: Union[str, int]) -> Dict[str, Any]:
        """Send test message to verify bot configuration."""
        try:
            test_text = "🤖 Test message from Animal Rescue Bot\nBot is working correctly!"
            
            message = TelegramMessage(
                chat_id=chat_id,
                text=test_text
            )
            
            success = await self.send_message(message)
            
            return {
                "status": "success" if success else "failed",
                "chat_id": chat_id,
                "bot_info": await self.get_bot_info()
            }
            
        except Exception as e:
            return {
                "status": "error",
                "chat_id": chat_id,
                "error": str(e)
            }
    
    async def get_bot_info(self) -> Dict[str, Any]:
        """Get bot information."""
        try:
            me = await self.bot.get_me()
            return {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "is_bot": me.is_bot,
                "can_join_groups": me.can_join_groups,
                "can_read_all_group_messages": me.can_read_all_group_messages,
                "supports_inline_queries": me.supports_inline_queries
            }
        except Exception as e:
            logger.error("Failed to get bot info", error=str(e))
            return {"error": str(e)}
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get service statistics."""
        total = self.stats['sent'] + self.stats['failed']
        return {
            "messages_sent": self.stats['sent'],
            "messages_failed": self.stats['failed'],
            "rate_limited": self.stats['rate_limited'],
            "success_rate": self.stats['sent'] / total if total > 0 else 0,
            "total_attempts": total
        }


# Global service instance
telegram_alerts = TelegramAlertsService()


# Convenience functions
async def send_new_report_alert(
    organization_chat_id: Union[str, int],
    report_data: Dict[str, Any],
    language: str = "he"
) -> bool:
    """Send new report alert to organization."""
    return await telegram_alerts.send_report_alert(
        organization_chat_id, report_data, language
    )


async def send_status_update_notification(
    chat_id: Union[str, int],
    report_data: Dict[str, Any],
    old_status: str,
    new_status: str,
    language: str = "he"
) -> bool:
    """Send status update notification."""
    return await telegram_alerts.send_status_update_alert(
        chat_id, report_data, old_status, new_status, language
    )


async def send_broadcast_message(
    chat_ids: List[Union[str, int]],
    message: str,
    language: str = "he"
) -> Dict[str, int]:
    """Send broadcast message to multiple chats."""
    return await telegram_alerts.send_bulk_alert(chat_ids, message, language=language)


async def test_telegram_service(chat_id: Union[str, int]) -> Dict[str, Any]:
    """Test Telegram service."""
    return await telegram_alerts.send_test_message(chat_id)


async def get_telegram_bot_info() -> Dict[str, Any]:
    """Get Telegram bot information."""
    return await telegram_alerts.get_bot_info()
