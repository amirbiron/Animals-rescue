"""
Telegram Bot Handlers
מטפלי הבוט של טלגרם

This module contains all Telegram bot message handlers for the Animal Rescue Bot.
Implements the complete user interaction flow from report creation to status tracking.
"""

import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Dict, List, Optional, Tuple

import structlog
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User as TelegramUser,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.core.config import settings
from app.core.cache import redis_client
from app.core.rate_limit import check_rate_limit, RateLimitExceeded
from app.models.database import async_session_maker, User, Report, ReportFile, UserSettings, Organization
from app.models.database import AnimalType, UrgencyLevel, ReportStatus, UserRole, OrganizationType
from app.services.nlp import NLPService
from app.services.geocoding import GeocodingService
from app.services.file_storage import FileStorageService
from app.workers.jobs import process_new_report, enqueue_or_run
from app.core.i18n import get_text, detect_language, set_user_language, get_user_language as i18n_get_user_language

# =============================================================================
# Constants and State Management
# =============================================================================

# Conversation states for report creation
(
    WAITING_FOR_PHOTO,
    WAITING_FOR_LOCATION,
    WAITING_FOR_DESCRIPTION,
    CONFIRMING_REPORT,
    SELECTING_URGENCY,
    SELECTING_ANIMAL_TYPE,
) = range(6)

# User session data keys
USER_DATA_KEYS = {
    "report_draft": "current_report",
    "language": "user_language",
    "photos": "uploaded_photos",
    "location": "report_location",
    "step": "conversation_step",
}

logger = structlog.get_logger(__name__)

# =============================================================================
# Services Initialization
# =============================================================================

nlp_service = NLPService()
geocoding_service = GeocodingService()
file_storage = FileStorageService()

# =============================================================================
# User Management Utilities
# =============================================================================

async def get_or_create_user(telegram_user: TelegramUser) -> User:
    """
    Get existing user or create new one from Telegram user data.
    
    Args:
        telegram_user: Telegram user object
        
    Returns:
        User instance from database
    """
    async with async_session_maker() as session:
        # Try to find existing user
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        result = await session.execute(
            select(User)
            .options(selectinload(User.settings))
            .where(User.telegram_user_id == telegram_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update user info if changed
            user.full_name = telegram_user.full_name
            user.username = telegram_user.username
            user.last_login_at = datetime.now(timezone.utc)
            
        else:
            # Create new user
            user = User(
                telegram_user_id=telegram_user.id,
                username=telegram_user.username,
                full_name=telegram_user.full_name,
                language=telegram_user.language_code or "he",
                role=UserRole.REPORTER,
                is_active=True,
                last_login_at=datetime.now(timezone.utc),
            )
            session.add(user)
        
        await session.commit()
        await session.refresh(user)
        return user


async def get_or_create_user_settings(user_id: uuid.UUID) -> UserSettings:
    """
    Get or create user settings.
    
    Args:
        user_id: User UUID
        
    Returns:
        UserSettings instance
    """
    async with async_session_maker() as session:
        from sqlalchemy import select
        
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = UserSettings(user_id=user_id)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        
        return settings


async def check_user_rate_limit(user_id: int, action: str) -> bool:
    """
    Check if user is within rate limits for specific action.
    
    Args:
        user_id: Telegram user ID
        action: Action being rate limited
        
    Returns:
        True if within limits, raises RateLimitExceeded if not
    """
    try:
        await check_rate_limit(
            client_id=f"telegram_user:{user_id}",
            resource=action,
            limit=settings.TELEGRAM_RATE_LIMIT_MESSAGES,
            window=settings.TELEGRAM_RATE_LIMIT_WINDOW,
        )
        return True
    except RateLimitExceeded as e:
        raise e


def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Get user's preferred language from context."""
    return context.user_data.get(USER_DATA_KEYS["language"], settings.DEFAULT_LANGUAGE)


def _normalize_hebrew_address(address: str) -> str:
    """Normalize common Hebrew address forms to improve geocoding success.
    למשל: "ת"א" => "תל אביב-יפו", הסרת גרשיים, המרת מקפים, טיפול בקיצורים.
    """
    if not address:
        return address
    text = address.strip()
    # Remove extraneous quotes
    text = text.replace('"', '').replace("'", "")
    # Common city abbreviations
    replacements = {
        "ת" + "א": "תל אביב-יפו",
        "ת א": "תל אביב-יפו",
        "ת" + "" + "א": "תל אביב-יפו",
        "ת" + '"' + "א": "תל אביב-יפו",
        "תל אביב": "תל אביב-יפו",
        "י-ם": "ירושלים",
        "ב" + '"' + "ש": "באר שבע",
        "ב" + '"' + "ש": "באר שבע",
        "ב" + '"' + "ש": "באר שבע",
    }
    for key, value in replacements.items():
        if key in text:
            text = text.replace(key, value)
    # Normalize dash variants
    text = text.replace("–", "-").replace("—", "-")
    return text


async def set_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show typing indicator to user."""
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )


# =============================================================================
# Command Handlers
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command - welcome new users and show main menu.
    """
    user = update.effective_user
    chat = update.effective_chat
    
    logger.info("User started bot", user_id=user.id, username=user.username)
    
    try:
        # Rate limiting
        await check_user_rate_limit(user.id, "start_command")
        
        # Get or create user in database
        db_user = await get_or_create_user(user)
        
        # Determine preferred language (default Hebrew)
        # 1) Use previously saved preference if exists
        # 2) Else use Telegram user language if supported
        # 3) Else fall back to DEFAULT_LANGUAGE (Hebrew)
        try:
            prev_lang = await i18n_get_user_language(db_user.id)
        except Exception:
            prev_lang = settings.DEFAULT_LANGUAGE
        telegram_lang = (user.language_code or "").lower() if getattr(user, "language_code", None) else None
        supported = set(settings.SUPPORTED_LANGUAGES)
        preferred_lang = prev_lang if prev_lang in supported else (telegram_lang if telegram_lang in supported else settings.DEFAULT_LANGUAGE)
        await set_user_language(db_user.id, preferred_lang)
        context.user_data[USER_DATA_KEYS["language"]] = preferred_lang
        
        # Show typing indicator
        await set_typing_action(update, context)
        
        # Welcome message
        welcome_text = get_text("welcome_message", preferred_lang).format(
            name=user.first_name or "משתמש",
            app_name=settings.APP_NAME
        )
        
        # Main menu keyboard - build based on user role
        keyboard = [
            [KeyboardButton(get_text("report_new_incident", preferred_lang))],
            [
                KeyboardButton(get_text("my_reports", preferred_lang)),
                KeyboardButton(get_text("user_settings", preferred_lang))
            ],
            [
                KeyboardButton(get_text("help", preferred_lang)),
                KeyboardButton(get_text("change_language", preferred_lang))
            ]
        ]
        
        # Add role-specific buttons
        if db_user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
            keyboard.append([
                KeyboardButton(get_text("org_reports_assigned", preferred_lang)),
                KeyboardButton(get_text("org_statistics", preferred_lang))
            ])
        # Also show org tools for system admins that are assigned to an organization
        if db_user.role == UserRole.SYSTEM_ADMIN and db_user.organization_id:
            keyboard.append([
                KeyboardButton(get_text("org_reports_assigned", preferred_lang)),
                KeyboardButton(get_text("org_statistics", preferred_lang))
            ])
        
        if db_user.role == UserRole.SYSTEM_ADMIN:
            keyboard.append([
                KeyboardButton(get_text("admin_users", preferred_lang)),
                KeyboardButton(get_text("admin_organizations", preferred_lang))
            ])
            keyboard.append([
                KeyboardButton(get_text("admin_reports", preferred_lang)),
                KeyboardButton(get_text("admin_settings", preferred_lang))
            ])
        
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        # reply safely whether message exists or only callback/effective_message
        target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if target_message is not None:
            await target_message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        
    except RateLimitExceeded as e:
        msg = get_text("rate_limit_exceeded", get_user_language(context))
        target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if target_message is not None:
            await target_message.reply_text(msg)
        
    except Exception as e:
        logger.error("Error in start command", error=str(e), exc_info=True)
        msg = get_text("error_generic", get_user_language(context))
        target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if target_message is not None:
            await target_message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command - show usage instructions."""
    lang = get_user_language(context)
    
    help_text = get_text("help_text", lang)
    
    # Emergency contacts
    emergency_text = get_text("emergency_contacts", lang)
    
    full_help = f"{help_text}\n\n{emergency_text}"
    
    await update.message.reply_text(
        full_help,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show user's recent reports."""
    user = update.effective_user
    lang = get_user_language(context)
    
    try:
        await check_user_rate_limit(user.id, "status_command")
        
        # Get user's recent reports
        async with async_session_maker() as session:
            from sqlalchemy import select, desc
            
            result = await session.execute(
                select(Report)
                .join(User)
                .where(User.telegram_user_id == user.id)
                .order_by(desc(Report.created_at))
                .limit(5)
            )
            reports = result.scalars().all()
        
        if not reports:
            await update.message.reply_text(
                get_text("no_reports_found", lang)
            )
            return
        
        # Format reports
        status_text = get_text("your_recent_reports", lang) + "\n\n"
        
        for report in reports:
            status_emoji = {
                ReportStatus.SUBMITTED: "🆕",
                ReportStatus.PENDING: "⏳", 
                ReportStatus.ACKNOWLEDGED: "✅",
                ReportStatus.IN_PROGRESS: "🔄",
                ReportStatus.RESOLVED: "✅",
                ReportStatus.CLOSED: "❌",
            }.get(report.status, "❓")
            
            status_text += f"{status_emoji} {report.public_id}\n"
            status_text += f"📅 {report.created_at.strftime('%d/%m %H:%M')}\n"
            status_text += f"📍 {report.city or get_text('location_unknown', lang)}\n"
            status_text += f"🔥 {get_text(f'urgency_{report.urgency_level.value}', lang)}\n"
            status_text += f"📋 {get_text(f'status_{report.status.value}', lang)}\n\n"
        
        # Add inline keyboard for detailed view
        keyboard = [
            [InlineKeyboardButton(
                get_text("view_detailed_status", lang),
                callback_data="detailed_status"
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            status_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
    except RateLimitExceeded:
        await update.message.reply_text(
            get_text("rate_limit_exceeded", lang)
        )
    except Exception as e:
        logger.error("Error in status command", error=str(e))
        await update.message.reply_text(
            get_text("error_generic", lang)
        )


# =============================================================================
# Report Creation Flow
# =============================================================================

async def start_report_creation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Start the report creation conversation flow.
    
    Returns:
        Next conversation state
    """
    user = update.effective_user
    lang = get_user_language(context)
    
    try:
        await check_user_rate_limit(user.id, "create_report")
        
        # Initialize report draft
        report_id = str(uuid.uuid4())
        context.user_data[USER_DATA_KEYS["report_draft"]] = {
            "id": report_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "photos": [],
            "language": lang,
        }
        
        # Clear previous location and photos
        context.user_data[USER_DATA_KEYS["photos"]] = []
        context.user_data[USER_DATA_KEYS["location"]] = None
        
        # Request photo
        instructions = get_text("request_photo_instructions", lang)
        
        # Remove main menu keyboard temporarily
        await update.message.reply_text(
            instructions,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML
        )
        
        return WAITING_FOR_PHOTO
        
    except RateLimitExceeded:
        await update.message.reply_text(
            get_text("rate_limit_exceeded", lang)
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error("Error starting report creation", error=str(e))
        await update.message.reply_text(
            get_text("error_generic", lang)
        )
        return ConversationHandler.END


async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle photo upload during report creation.
    
    Returns:
        Next conversation state
    """
    lang = get_user_language(context)
    
    try:
        await set_typing_action(update, context)
        
        # Get photo file
        photo = update.message.photo[-1]  # Get highest resolution
        photo_file = await photo.get_file()
        
        # Download photo data
        photo_data = BytesIO()
        await photo_file.download_to_memory(photo_data)
        photo_data.seek(0)
        
        # Generate unique filename
        file_hash = hashlib.sha256(photo_data.getvalue()).hexdigest()[:16]
        filename = f"report_photo_{file_hash}.jpg"
        
        # Store photo temporarily
        photo_info = {
            "file_id": photo.file_id,
            "filename": filename,
            "file_size": photo.file_size,
            "width": photo.width,
            "height": photo.height,
            "data": photo_data.getvalue(),
            "hash": file_hash,
        }
        
        # Add to user data
        if USER_DATA_KEYS["photos"] not in context.user_data:
            context.user_data[USER_DATA_KEYS["photos"]] = []
        
        context.user_data[USER_DATA_KEYS["photos"]].append(photo_info)
        
        # Check if user wants to add more photos
        current_count = len(context.user_data[USER_DATA_KEYS["photos"]])
        max_photos = 3
        
        if current_count < max_photos:
            # Option to add more photos or continue
            keyboard = [
                [KeyboardButton(get_text("add_another_photo", lang))],
                [KeyboardButton(get_text("continue_with_location", lang))]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            message = get_text("photo_uploaded_success", lang).format(
                current=current_count,
                max=max_photos
            )
            
            await update.message.reply_text(
                message,
                reply_markup=reply_markup
            )
            
            return WAITING_FOR_PHOTO  # Stay in same state
        else:
            # Maximum photos reached, move to location
            await update.message.reply_text(
                get_text("max_photos_reached", lang)
            )
            return await request_location(update, context)
            
    except Exception as e:
        logger.error("Error handling photo upload", error=str(e))
        await update.message.reply_text(
            get_text("error_photo_upload", lang)
        )
        return WAITING_FOR_PHOTO


async def request_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Request location from user.
    
    Returns:
        Next conversation state
    """
    lang = get_user_language(context)
    
    # Location request message
    location_text = get_text("request_location_instructions", lang)
    
    # Keyboard with location sharing button
    keyboard = [
        [KeyboardButton(
            get_text("share_location", lang),
            request_location=True
        )],
        [KeyboardButton(get_text("enter_address_manually", lang))]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    msg_target = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
    if msg_target is not None:
        await msg_target.reply_text(
            location_text,
            reply_markup=reply_markup
        )
    
    return WAITING_FOR_LOCATION


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle location data (GPS or manual address).
    
    Returns:
        Next conversation state
    """
    lang = get_user_language(context)
    
    try:
        await set_typing_action(update, context)
        
        location_data = None
        
        if getattr(update, 'message', None) and update.message.location:
            # GPS location received
            location = update.message.location
            location_data = {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "accuracy": getattr(location, "horizontal_accuracy", None),
                "type": "gps",
            }
            
            # Reverse geocode to get address
            try:
                address_info = await geocoding_service.reverse_geocode(
                    location.latitude, location.longitude
                )
                if address_info:
                    location_data.update(address_info)
                else:
                    location_data["address"] = get_text("address_unavailable", lang)
                    location_data["city"] = None
            except Exception as e:
                logger.warning("Reverse geocoding failed", error=str(e))
                location_data["address"] = get_text("address_unavailable", lang)
                location_data["city"] = None
            
        elif getattr(update, 'message', None) and update.message.text:
            # Manual address entered
            address = update.message.text.strip()
            
            # Skip if it's a button press
            button_texts = [
                get_text("enter_address_manually", lang),
                get_text("share_location", lang)
            ]
            if address in button_texts:
                return WAITING_FOR_LOCATION
            
            try:
                # Geocode address
                # Normalize common Hebrew city abbreviations before geocoding
                normalized = _normalize_hebrew_address(address)
                geocode_result = await geocoding_service.geocode(normalized)
                if geocode_result:
                    location_data = {
                        "address": address,
                        "latitude": geocode_result["latitude"],
                        "longitude": geocode_result["longitude"],
                        "city": geocode_result.get("city"),
                        "confidence": geocode_result.get("confidence", 0.5),
                        "type": "manual",
                    }
                else:
                    await update.message.reply_text(
                        get_text("address_not_found", lang)
                    )
                    return WAITING_FOR_LOCATION
                    
            except Exception as e:
                logger.error("Geocoding failed", error=str(e))
                await update.message.reply_text(
                    get_text("error_geocoding", lang)
                )
                return WAITING_FOR_LOCATION
        
        if not location_data:
            return WAITING_FOR_LOCATION
        
        # Store location data
        context.user_data[USER_DATA_KEYS["location"]] = location_data
        
        # Confirm location
        confirmation_text = get_text("location_confirmed", lang).format(
            address=(location_data.get("address") or location_data.get("formatted_address") or get_text("coordinates_only", lang)),
            city=(location_data.get("city") or get_text("unknown_city", lang))
        )
        
        msg_target = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if msg_target is not None:
            await msg_target.reply_text(
                confirmation_text,
                reply_markup=ReplyKeyboardRemove()
            )
        
        # Move to description
        return await request_description(update, context)
        
    except Exception as e:
        logger.error("Error handling location", error=str(e))
        await update.message.reply_text(
            get_text("error_location", lang)
        )
        return WAITING_FOR_LOCATION


async def request_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Request incident description from user.
    
    Returns:
        Next conversation state
    """
    lang = get_user_language(context)
    
    description_text = get_text("request_description_instructions", lang)
    
    await update.message.reply_text(
        description_text,
        parse_mode=ParseMode.HTML
    )
    
    return WAITING_FOR_DESCRIPTION


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle incident description and perform NLP analysis.
    
    Returns:
        Next conversation state
    """
    lang = get_user_language(context)
    description = (getattr(update, 'message', None) and update.message.text or "").strip()
    
    if not description or len(description) < 10:
        target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if target_message is not None:
            await target_message.reply_text(
                get_text("description_too_short", lang)
            )
        return WAITING_FOR_DESCRIPTION
    
    try:
        await set_typing_action(update, context)
        
        # Perform NLP analysis
        nlp_results = await nlp_service.analyze_text(description, lang)
        
        # Store description and analysis
        report_draft = context.user_data[USER_DATA_KEYS["report_draft"]]
        report_draft.update({
            "description": description,
            "urgency_level": nlp_results.get("urgency", UrgencyLevel.MEDIUM),
            "animal_type": nlp_results.get("animal_type", AnimalType.UNKNOWN),
            "keywords": nlp_results.get("keywords", []),
            "sentiment": nlp_results.get("sentiment", 0.0),
        })
        
        # Generate automatic title
        title = await nlp_service.generate_title(description, lang)
        report_draft["title"] = title
        
        # Show analysis results and ask for confirmation
        analysis_text = get_text("nlp_analysis_results", lang).format(
            title=title,
            urgency=get_text(f"urgency_{report_draft['urgency_level'].value}", lang),
            animal_type=get_text(f"animal_{report_draft['animal_type'].value}", lang)
        )
        
        # Confirmation keyboard
        keyboard = [
            [
                InlineKeyboardButton(
                    get_text("correct_continue", lang),
                    callback_data="confirm_analysis"
                )
            ],
            [
                InlineKeyboardButton(
                    get_text("modify_urgency", lang),
                    callback_data="modify_urgency"
                ),
                InlineKeyboardButton(
                    get_text("modify_animal_type", lang),
                    callback_data="modify_animal_type"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            analysis_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
        return CONFIRMING_REPORT
        
    except Exception as e:
        logger.error("Error handling description", error=str(e))
        target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
        if target_message is not None:
            await target_message.reply_text(
                get_text("error_description", lang)
            )
        return WAITING_FOR_DESCRIPTION


# =============================================================================
# Report Confirmation and Submission
# =============================================================================

async def handle_report_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle report confirmation callbacks."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    action = query.data
    
    if action == "confirm_analysis":
        return await submit_report(update, context)
    elif action == "modify_urgency":
        return await show_urgency_selection(update, context)
    elif action == "modify_animal_type":
        return await show_animal_type_selection(update, context)
    
    return CONFIRMING_REPORT


async def show_urgency_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show urgency level selection."""
    lang = get_user_language(context)
    
    keyboard = []
    for urgency in UrgencyLevel:
        emoji = {
            UrgencyLevel.LOW: "🟢",
            UrgencyLevel.MEDIUM: "🟡", 
            UrgencyLevel.HIGH: "🟠",
            UrgencyLevel.CRITICAL: "🔴"
        }[urgency]
        
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {get_text(f'urgency_{urgency.value}', lang)}",
            callback_data=f"urgency_{urgency.value}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        get_text("select_urgency_level", lang),
        reply_markup=reply_markup
    )
    
    return SELECTING_URGENCY


async def show_animal_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show animal type selection."""
    lang = get_user_language(context)
    
    keyboard = []
    for animal_type in [AnimalType.DOG, AnimalType.CAT, AnimalType.BIRD, 
                       AnimalType.WILDLIFE, AnimalType.OTHER]:
        emoji = {
            AnimalType.DOG: "🐕",
            AnimalType.CAT: "🐱",
            AnimalType.BIRD: "🐦",
            AnimalType.WILDLIFE: "🦌",
            AnimalType.OTHER: "❓"
        }.get(animal_type, "❓")
        
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {get_text(f'animal_{animal_type.value}', lang)}",
            callback_data=f"animal_{animal_type.value}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        get_text("select_animal_type", lang),
        reply_markup=reply_markup
    )
    
    return SELECTING_ANIMAL_TYPE


async def handle_urgency_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle urgency level selection."""
    query = update.callback_query
    await query.answer()
    
    urgency_value = query.data.replace("urgency_", "")
    urgency = UrgencyLevel(urgency_value)
    
    # Update report draft
    context.user_data[USER_DATA_KEYS["report_draft"]]["urgency_level"] = urgency
    
    return await submit_report(update, context)


async def handle_animal_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle animal type selection."""
    query = update.callback_query
    await query.answer()
    
    animal_value = query.data.replace("animal_", "")
    animal_type = AnimalType(animal_value)
    
    # Update report draft
    context.user_data[USER_DATA_KEYS["report_draft"]]["animal_type"] = animal_type
    
    return await submit_report(update, context)


async def submit_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Submit the complete report to the database and trigger alerts.
    
    Returns:
        ConversationHandler.END to finish the conversation
    """
    lang = get_user_language(context)
    user = update.effective_user
    
    try:
        await set_typing_action(update, context)
        
        # Get report draft
        report_draft = context.user_data.get(USER_DATA_KEYS["report_draft"])
        if not report_draft:
            raise ValueError("No report draft found")
        
        # Get location and photos
        location_data = context.user_data.get(USER_DATA_KEYS["location"])
        photos = context.user_data.get(USER_DATA_KEYS["photos"], [])
        
        if not location_data:
            raise ValueError("No location data found")
        
        # Get user from database
        db_user = await get_or_create_user(user)
        
        # Create report in database
        async with async_session_maker() as session:
            # Create report instance
            report = Report(
                reporter_id=db_user.id,
                title=report_draft["title"],
                description=report_draft["description"],
                animal_type=report_draft["animal_type"],
                urgency_level=report_draft["urgency_level"],
                status=ReportStatus.SUBMITTED,
                language=lang,
                # Location data
                latitude=location_data["latitude"],
                longitude=location_data["longitude"],
                address=location_data.get("address"),
                city=location_data.get("city"),
                location_accuracy_meters=location_data.get("accuracy"),
                address_verified=location_data.get("confidence", 0) > 0.7,
                # NLP results
                keywords=report_draft.get("keywords", []),
                sentiment_score=report_draft.get("sentiment"),
            )
            
            session.add(report)
            await session.flush()  # Get the report ID
            
            # Upload and store photos
            for photo_info in photos:
                try:
                    # Upload to storage
                    storage_result = await file_storage.upload_file(
                        file_data=photo_info["data"],
                        filename=photo_info["filename"],
                        content_type="image/jpeg",
                        folder=f"reports/{report.id}"
                    )
                    
                    # Create file record
                    report_file = ReportFile(
                        report_id=report.id,
                        filename=photo_info["filename"],
                        file_type="photo",
                        mime_type="image/jpeg",
                        file_size_bytes=len(photo_info["data"]),
                        storage_backend=settings.STORAGE_BACKEND,
                        storage_path=storage_result["path"],
                        storage_url=storage_result.get("url"),
                        width=photo_info["width"],
                        height=photo_info["height"],
                        file_hash=photo_info["hash"],
                    )
                    
                    session.add(report_file)
                    
                except Exception as e:
                    logger.error("Failed to upload photo", error=str(e))
                    # Continue with other photos
            
            await session.commit()
            await session.refresh(report)
        
        # Queue background jobs (or run inline when workers disabled)
        enqueue_or_run(process_new_report, str(report.id))
        
        # Success message
        success_text = get_text("report_submitted_success", lang).format(
            report_id=report.public_id,
            urgency=get_text(f"urgency_{report.urgency_level.value}", lang),
            animal_type=get_text(f"animal_{report.animal_type.value}", lang)
        )
        
        # Add tracking keyboard
        keyboard = [
            [InlineKeyboardButton(
                get_text("track_report", lang),
                callback_data=f"track_{report.public_id}"
            )],
            [InlineKeyboardButton(
                get_text("share_report", lang), 
                callback_data=f"share_{report.public_id}"
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
            if target_message is not None:
                await target_message.reply_text(
                    success_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
        
        # Clean up user data
        context.user_data.clear()
        
        # Show main menu again
        await asyncio.sleep(2)  # Brief pause
        try:
            await start_command(update, context)
        except Exception as e:
            # Do not fail the flow if welcome/menu fails; just log and continue
            logger.warning("Failed to show main menu after submission", error=str(e))
        
        # Update metrics
        from app.main import REPORTS_CREATED
        REPORTS_CREATED.labels(
            urgency_level=report.urgency_level.value,
            animal_type=report.animal_type.value
        ).inc()
        
        logger.info(
            "Report submitted successfully",
            report_id=str(report.id),
            public_id=report.public_id,
            user_id=user.id,
            urgency=report.urgency_level.value,
            animal_type=report.animal_type.value
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error("Error submitting report", error=str(e), exc_info=True)
        
        error_text = get_text("error_submit_report", lang)
        if update.callback_query:
            await update.callback_query.message.reply_text(error_text)
        else:
            # Avoid sending error after we already showed success
            # Only send error if we have not announced success yet (no reply_markup in recent message)
            try:
                target_message = getattr(update, 'message', None) or getattr(update, 'effective_message', None)
                if target_message is not None:
                    await target_message.reply_text(error_text)
            except Exception:
                pass
        
        return ConversationHandler.END


# =============================================================================
# User Settings Handlers
# =============================================================================

async def show_user_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user settings menu."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Get user from database
    db_user = await get_or_create_user(user)
    
    # Build settings menu
    keyboard = [
        [InlineKeyboardButton(
            get_text("my_service_area", lang),
            callback_data="settings_service_area"
        )],
        [InlineKeyboardButton(
            get_text("notification_settings", lang),
            callback_data="settings_notifications"
        )],
        [InlineKeyboardButton(
            get_text("contact_details", lang),
            callback_data="settings_contact"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data="settings_back"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = get_text("user_settings", lang)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)


async def handle_service_area_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle service area settings."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    
    # Show radius options
    keyboard = [
        [InlineKeyboardButton("5 ק\"מ", callback_data="service_radius_5")],
        [InlineKeyboardButton("10 ק\"מ", callback_data="service_radius_10")],
        [InlineKeyboardButton("20 ק\"מ", callback_data="service_radius_20")],
        [InlineKeyboardButton("50 ק\"מ", callback_data="service_radius_50")],
        [InlineKeyboardButton(
            get_text("no_location_alerts", lang),
            callback_data="service_radius_0"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data="settings_menu"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"{get_text('service_area_title', lang)}\n\n{get_text('service_area_instructions', lang)}"
    
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_service_radius_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle service area radius selection."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    data = query.data.replace("service_radius_", "")
    radius = int(data)
    
    # Get user
    db_user = await get_or_create_user(update.effective_user)
    settings = await get_or_create_user_settings(db_user.id)
    
    if radius == 0:
        # Disable location alerts
        async with async_session_maker() as session:
            settings = await session.get(UserSettings, settings.id)
            settings.service_area_enabled = False
            settings.service_area_radius_km = None
            await session.commit()
        
        await query.edit_message_text(get_text("service_area_disabled", lang))
    else:
        # Request location to set service area center
        context.user_data["pending_service_radius"] = radius
        
        keyboard = [
            [KeyboardButton(
                get_text("share_location", lang),
                request_location=True
            )],
            [KeyboardButton(get_text("cancel", lang))]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await query.message.reply_text(
            get_text("request_location_for_service", lang),
            reply_markup=reply_markup
        )


async def handle_service_area_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle location for service area setup."""
    if not update.message.location:
        return
    
    lang = get_user_language(context)
    radius = context.user_data.get("pending_service_radius")
    
    if not radius:
        return
    
    location = update.message.location
    
    # Save service area settings
    db_user = await get_or_create_user(update.effective_user)
    
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == db_user.id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = UserSettings(user_id=db_user.id)
            session.add(settings)
        
        settings.service_area_enabled = True
        settings.service_area_radius_km = float(radius)
        settings.service_area_latitude = location.latitude
        settings.service_area_longitude = location.longitude
        
        await session.commit()
    
    # Clear pending data
    context.user_data.pop("pending_service_radius", None)
    
    # Show confirmation
    await update.message.reply_text(
        get_text("service_area_updated", lang).format(radius=radius),
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Return to main menu
    await start_command(update, context)


async def handle_notification_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle notification settings menu."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("notif_my_reports", lang),
            callback_data="notif_category_my"
        )],
        [InlineKeyboardButton(
            get_text("notif_area_reports", lang),
            callback_data="notif_category_area"
        )],
        [InlineKeyboardButton(
            get_text("notif_system", lang),
            callback_data="notif_category_system"
        )],
        [InlineKeyboardButton(
            get_text("quiet_hours", lang),
            callback_data="notif_quiet_hours"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data="settings_menu"
        )]
    ]
    
    # Add org notifications for staff
    db_user = await get_or_create_user(update.effective_user)
    if db_user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
        keyboard.insert(3, [InlineKeyboardButton(
            get_text("notif_org_operational", lang),
            callback_data="notif_category_org"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"{get_text('notifications_title', lang)}\n\n{get_text('notifications_menu', lang)}"
    
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_quiet_hours_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show and control quiet hours settings."""
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    
    db_user = await get_or_create_user(update.effective_user)
    user_settings = await get_or_create_user_settings(db_user.id)
    
    if user_settings.quiet_hours_enabled and user_settings.quiet_hours_start and user_settings.quiet_hours_end:
        status_text = get_text("quiet_hours_enabled", lang).format(
            start=user_settings.quiet_hours_start,
            end=user_settings.quiet_hours_end,
        )
    else:
        status_text = get_text("quiet_hours_disabled", lang)
    
    keyboard = [
        [InlineKeyboardButton(get_text("set_quiet_hours", lang), callback_data="quiet_hours_set")],
        [InlineKeyboardButton(get_text("disable_quiet_hours", lang), callback_data="quiet_hours_disable")],
        [InlineKeyboardButton(get_text("back", lang), callback_data="settings_notifications")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"{get_text('quiet_hours_menu', lang)}\n\n{status_text}\n\n{get_text('quiet_hours_instructions', lang)}"
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_quiet_hours_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to enter quiet hours time range."""
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    context.user_data["awaiting_quiet_hours"] = True
    keyboard = [[InlineKeyboardButton(get_text("back", lang), callback_data="settings_notifications")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(get_text("quiet_hours_instructions", lang), reply_markup=reply_markup)


async def handle_quiet_hours_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable quiet hours immediately."""
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    
    db_user = await get_or_create_user(update.effective_user)
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(select(UserSettings).where(UserSettings.user_id == db_user.id))
        user_settings = result.scalar_one_or_none()
        if not user_settings:
            user_settings = UserSettings(user_id=db_user.id)
            session.add(user_settings)
        user_settings.quiet_hours_enabled = False
        user_settings.quiet_hours_start = None
        user_settings.quiet_hours_end = None
        await session.commit()
    
    await query.edit_message_text(get_text("quiet_hours_disabled", lang))


async def handle_quiet_hours_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user text input for quiet hours time range (e.g., 22:00-07:00)."""
    if not context.user_data.get("awaiting_quiet_hours"):
        return
    lang = get_user_language(context)
    text = (getattr(update, 'message', None) and update.message.text or '').strip()
    match = re.match(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$", text)
    if not match:
        await update.message.reply_text(get_text("quiet_hours_instructions", lang))
        return
    h1, m1, h2, m2 = map(int, match.groups())
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
        await update.message.reply_text(get_text("quiet_hours_instructions", lang))
        return
    start_s = f"{h1:02d}:{m1:02d}"
    end_s = f"{h2:02d}:{m2:02d}"
    
    db_user = await get_or_create_user(update.effective_user)
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(select(UserSettings).where(UserSettings.user_id == db_user.id))
        user_settings = result.scalar_one_or_none()
        if not user_settings:
            user_settings = UserSettings(user_id=db_user.id)
            session.add(user_settings)
        user_settings.quiet_hours_enabled = True
        user_settings.quiet_hours_start = start_s
        user_settings.quiet_hours_end = end_s
        await session.commit()
    
    context.user_data.pop("awaiting_quiet_hours", None)
    keyboard = [[InlineKeyboardButton(get_text("back", lang), callback_data="settings_notifications")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_text("quiet_hours_updated", lang).format(start=start_s, end=end_s),
        reply_markup=reply_markup
    )


async def handle_notification_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle specific notification category settings."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    category = query.data.replace("notif_category_", "")
    
    # Get current settings
    db_user = await get_or_create_user(update.effective_user)
    settings = await get_or_create_user_settings(db_user.id)
    
    # Build menu based on category
    keyboard = []
    
    if category == "my":
        notifications = [
            ("notif_status_updates", settings.notif_status_updates),
            ("notif_org_messages", settings.notif_org_messages),
            ("notif_info_requests", settings.notif_info_requests),
        ]
        menu_text = get_text("notif_my_reports_menu", lang)
    elif category == "area":
        notifications = [
            ("notif_new_nearby", settings.notif_new_nearby),
            ("notif_urgent_nearby", settings.notif_urgent_nearby),
            ("notif_help_requests", settings.notif_help_requests),
        ]
        menu_text = get_text("notif_area_menu", lang)
    elif category == "system":
        notifications = [
            ("notif_admin_messages", settings.notif_admin_messages),
            ("notif_updates_news", settings.notif_updates_news),
            ("notif_reminders", settings.notif_reminders),
        ]
        menu_text = get_text("notif_system_menu", lang)
    elif category == "org":
        notifications = [
            ("notif_new_assigned", settings.notif_new_assigned),
            ("notif_pending_reminders", settings.notif_pending_reminders),
            ("notif_performance_updates", settings.notif_performance_updates),
        ]
        menu_text = get_text("notif_org_menu", lang)
    else:
        return
    
    # Create toggle buttons
    for notif_key, enabled in notifications:
        icon = "✅" if enabled else "❌"
        text = get_text(notif_key, lang)
        keyboard.append([InlineKeyboardButton(
            f"{icon} {text}",
            callback_data=f"toggle_{notif_key}"
        )])
    
    keyboard.append([InlineKeyboardButton(
        get_text("back", lang),
        callback_data="settings_notifications"
    )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(menu_text, reply_markup=reply_markup)


async def handle_notification_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle specific notification setting."""
    query = update.callback_query
    await query.answer()
    
    setting_key = query.data.replace("toggle_", "")
    
    # Update setting in database
    db_user = await get_or_create_user(update.effective_user)
    
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == db_user.id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = UserSettings(user_id=db_user.id)
            session.add(settings)
        
        # Toggle the setting
        current_value = getattr(settings, setting_key, False)
        setattr(settings, setting_key, not current_value)
        
        await session.commit()
    
    # Refresh the menu without mutating CallbackQuery
    if setting_key in ["notif_status_updates", "notif_org_messages", "notif_info_requests"]:
        category = "my"
    elif setting_key in ["notif_new_nearby", "notif_urgent_nearby", "notif_help_requests"]:
        category = "area"
    elif setting_key in ["notif_admin_messages", "notif_updates_news", "notif_reminders"]:
        category = "system"
    else:
        category = "org"
    lang = get_user_language(context)
    # Fetch current settings
    db_user = await get_or_create_user(update.effective_user)
    settings = await get_or_create_user_settings(db_user.id)
    # Build the category menu
    keyboard = []
    if category == "my":
        notifications = [
            ("notif_status_updates", settings.notif_status_updates),
            ("notif_org_messages", settings.notif_org_messages),
            ("notif_info_requests", settings.notif_info_requests),
        ]
        menu_text = get_text("notif_my_reports_menu", lang)
    elif category == "area":
        notifications = [
            ("notif_new_nearby", settings.notif_new_nearby),
            ("notif_urgent_nearby", settings.notif_urgent_nearby),
            ("notif_help_requests", settings.notif_help_requests),
        ]
        menu_text = get_text("notif_area_menu", lang)
    elif category == "system":
        notifications = [
            ("notif_admin_messages", settings.notif_admin_messages),
            ("notif_updates_news", settings.notif_updates_news),
            ("notif_reminders", settings.notif_reminders),
        ]
        menu_text = get_text("notif_system_menu", lang)
    else:
        notifications = [
            ("notif_new_assigned", settings.notif_new_assigned),
            ("notif_pending_reminders", settings.notif_pending_reminders),
            ("notif_performance_updates", settings.notif_performance_updates),
        ]
        menu_text = get_text("notif_org_menu", lang)
    for notif_key, enabled in notifications:
        icon = "✅" if enabled else "❌"
        text = get_text(notif_key, lang)
        keyboard.append([InlineKeyboardButton(f"{icon} {text}", callback_data=f"toggle_{notif_key}")])
    keyboard.append([InlineKeyboardButton(get_text("back", lang), callback_data="settings_notifications")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(menu_text, reply_markup=reply_markup)


async def handle_contact_details_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle contact details settings."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    
    # Get current user details
    db_user = await get_or_create_user(update.effective_user)
    settings = await get_or_create_user_settings(db_user.id)
    
    # Show current details
    current_phone = db_user.phone or settings.secondary_phone or get_text("no", lang)
    current_email = db_user.email or settings.secondary_email or get_text("no", lang)
    
    text = get_text("contact_details_current", lang).format(
        phone=current_phone,
        email=current_email
    )
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("update_phone", lang),
            callback_data="contact_update_phone"
        )],
        [InlineKeyboardButton(
            get_text("update_email", lang),
            callback_data="contact_update_email"
        )],
        [InlineKeyboardButton(
            get_text("add_emergency_contact", lang),
            callback_data="contact_emergency"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data="settings_menu"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_contact_update_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to update primary phone number."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_phone"] = True
    await query.edit_message_text("אנא שלחו מספר טלפון בפורמט תקין (לדוגמה: 050-1234567)")


async def handle_contact_update_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to update primary email address."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_email"] = True
    await query.edit_message_text("אנא שלחו כתובת אימייל תקינה (לדוגמה: name@example.com)")


async def handle_contact_emergency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to update emergency contact phone."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_emergency_phone"] = True
    await query.edit_message_text("שלחו מספר טלפון של איש קשר לחירום")


async def handle_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle phone number input for various flows."""
    text = (getattr(update, 'message', None) and update.message.text or '').strip()
    if not any([
        context.user_data.get("awaiting_phone"),
        context.user_data.get("awaiting_emergency_phone"),
    ]):
        return
    normalized = re.sub(r"[^\d+]", "", text)
    if not re.match(r"^\+?\d{7,15}$", normalized):
        await update.message.reply_text("מספר לא תקין. נסו שוב.")
        return
    db_user = await get_or_create_user(update.effective_user)
    if context.user_data.get("awaiting_phone"):
        async with async_session_maker() as session:
            user = await session.get(User, db_user.id)
            user.phone = normalized
            await session.commit()
        context.user_data.pop("awaiting_phone", None)
        await update.message.reply_text("מספר הטלפון עודכן ✅")
        return
    if context.user_data.get("awaiting_emergency_phone"):
        async with async_session_maker() as session:
            from sqlalchemy import select
            result = await session.execute(select(UserSettings).where(UserSettings.user_id == db_user.id))
            user_settings = result.scalar_one_or_none()
            if not user_settings:
                user_settings = UserSettings(user_id=db_user.id)
                session.add(user_settings)
            user_settings.emergency_contact_phone = normalized
            await session.commit()
        context.user_data.pop("awaiting_emergency_phone", None)
        await update.message.reply_text("איש קשר חירום עודכן ✅")


async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle email address input for contact details."""
    if not context.user_data.get("awaiting_email"):
        return
    text = (getattr(update, 'message', None) and update.message.text or '').strip()
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", text):
        await update.message.reply_text("אימייל לא תקין. נסו שוב.")
        return
    db_user = await get_or_create_user(update.effective_user)
    async with async_session_maker() as session:
        user = await session.get(User, db_user.id)
        user.email = text
        await session.commit()
    context.user_data.pop("awaiting_email", None)
    await update.message.reply_text("האימייל עודכן ✅")


# =============================================================================
# Organization Staff Handlers
# =============================================================================

async def show_assigned_reports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show reports assigned to organization."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Get user and check permissions
    db_user = await get_or_create_user(user)
    
    if db_user.role not in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    if not db_user.organization_id:
        await update.message.reply_text(get_text("no_organization", lang))
        return
    
    # Get assigned reports
    async with async_session_maker() as session:
        from sqlalchemy import select, desc
        
        result = await session.execute(
            select(Report)
            .where(Report.assigned_organization_id == db_user.organization_id)
            .where(Report.status.in_([
                ReportStatus.SUBMITTED,
                ReportStatus.PENDING,
                ReportStatus.ACKNOWLEDGED,
                ReportStatus.IN_PROGRESS
            ]))
            .order_by(desc(Report.urgency_level), desc(Report.created_at))
            .limit(10)
        )
        reports = result.scalars().all()
    
    if not reports:
        await update.message.reply_text(get_text("no_assigned_reports", lang))
        return
    
    # Format reports list
    text = get_text("assigned_reports_title", lang) + "\n\n"
    keyboard = []
    
    for report in reports:
        # Add report details to text
        text += get_text("report_details", lang).format(
            report_id=report.public_id,
            location=report.city or report.address or get_text("location_unknown", lang),
            urgency=get_text(f"urgency_{report.urgency_level.value}", lang),
            animal_type=get_text(f"animal_{report.animal_type.value}", lang),
            status=get_text(f"status_{report.status.value}", lang),
            created_at=report.created_at.strftime("%d/%m %H:%M")
        ) + "\n\n"
        
        # Add action button
        keyboard.append([InlineKeyboardButton(
            f"#{report.public_id} - {get_text('select_report_action', lang)}",
            callback_data=f"org_report_{report.public_id}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)


async def handle_org_report_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle organization report action selection."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    report_id = query.data.replace("org_report_", "")
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("acknowledge_report", lang),
            callback_data=f"org_ack_{report_id}"
        )],
        [InlineKeyboardButton(
            get_text("update_report_status", lang),
            callback_data=f"org_status_{report_id}"
        )],
        [InlineKeyboardButton(
            get_text("view_full_details", lang),
            callback_data=f"org_details_{report_id}"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data="org_reports_list"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        get_text("select_report_action", lang),
        reply_markup=reply_markup
    )


async def handle_org_reports_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to assigned reports list from org submenu."""
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    user = update.effective_user
    
    # Get user and check permissions
    db_user = await get_or_create_user(user)
    allowed_roles = [UserRole.ORG_STAFF, UserRole.ORG_ADMIN, UserRole.SYSTEM_ADMIN]
    if db_user.role not in allowed_roles or not db_user.organization_id:
        await query.edit_message_text(get_text("permission_denied", lang))
        return
    
    # Get assigned reports
    async with async_session_maker() as session:
        from sqlalchemy import select, desc
        result = await session.execute(
            select(Report)
            .where(Report.assigned_organization_id == db_user.organization_id)
            .where(Report.status.in_([
                ReportStatus.SUBMITTED,
                ReportStatus.PENDING,
                ReportStatus.ACKNOWLEDGED,
                ReportStatus.IN_PROGRESS
            ]))
            .order_by(desc(Report.urgency_level), desc(Report.created_at))
            .limit(10)
        )
        reports = result.scalars().all()
    
    if not reports:
        await query.edit_message_text(get_text("no_assigned_reports", lang))
        return
    
    text = get_text("assigned_reports_title", lang) + "\n\n"
    keyboard = []
    for report in reports:
        text += get_text("report_details", lang).format(
            report_id=report.public_id,
            location=report.city or report.address or get_text("location_unknown", lang),
            urgency=get_text(f"urgency_{report.urgency_level.value}", lang),
            animal_type=get_text(f"animal_{report.animal_type.value}", lang),
            status=get_text(f"status_{report.status.value}", lang),
            created_at=report.created_at.strftime("%d/%m %H:%M")
        ) + "\n\n"
        keyboard.append([InlineKeyboardButton(
            f"#{report.public_id} - {get_text('select_report_action', lang)}",
            callback_data=f"org_report_{report.public_id}"
        )])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_org_report_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show full details for a specific report in org context."""
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    public_id = query.data.replace("org_details_", "")
    
    # Get report
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(select(Report).where(Report.public_id == public_id))
        report = result.scalar_one_or_none()
    if not report:
        await query.edit_message_text(get_text("report_not_found", lang))
        return
    
    text = get_text("report_details", lang).format(
        report_id=report.public_id,
        location=report.city or report.address or get_text("location_unknown", lang),
        urgency=get_text(f"urgency_{report.urgency_level.value}", lang),
        animal_type=get_text(f"animal_{report.animal_type.value}", lang),
        status=get_text(f"status_{report.status.value}", lang),
        created_at=report.created_at.strftime("%d/%m %H:%M")
    )
    keyboard = [[InlineKeyboardButton(get_text("back", lang), callback_data=f"org_report_{public_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_org_acknowledge_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle report acknowledgement by organization."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    report_id = query.data.replace("org_ack_", "")
    
    # Update report status
    async with async_session_maker() as session:
        from sqlalchemy import select
        
        result = await session.execute(
            select(Report).where(Report.public_id == report_id)
        )
        report = result.scalar_one_or_none()
        
        if report and report.status in [ReportStatus.SUBMITTED, ReportStatus.PENDING]:
            report.status = ReportStatus.ACKNOWLEDGED
            report.first_response_at = datetime.now(timezone.utc)
            await session.commit()
            
            await query.edit_message_text(
                get_text("acknowledge_success", lang).format(report_id=report_id)
            )
        else:
            await query.edit_message_text(
                get_text("operation_failed", lang)
            )


async def handle_org_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle report status update by organization."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    report_id = query.data.replace("org_status_", "")
    
    # Show status options
    keyboard = [
        [InlineKeyboardButton(
            get_text("status_acknowledged_desc", lang),
            callback_data=f"set_status_{report_id}_acknowledged"
        )],
        [InlineKeyboardButton(
            get_text("status_in_progress_desc", lang),
            callback_data=f"set_status_{report_id}_in_progress"
        )],
        [InlineKeyboardButton(
            get_text("status_resolved_desc", lang),
            callback_data=f"set_status_{report_id}_resolved"
        )],
        [InlineKeyboardButton(
            get_text("status_closed_desc", lang),
            callback_data=f"set_status_{report_id}_closed"
        )],
        [InlineKeyboardButton(
            get_text("back", lang),
            callback_data=f"org_report_{report_id}"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        get_text("select_new_status", lang).format(report_id=report_id),
        reply_markup=reply_markup
    )


async def handle_set_report_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set report status."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    parts = query.data.split("_")
    report_id = parts[2]
    new_status = parts[3]
    
    # Update status in database
    async with async_session_maker() as session:
        from sqlalchemy import select
        
        result = await session.execute(
            select(Report).where(Report.public_id == report_id)
        )
        report = result.scalar_one_or_none()
        
        if report:
            # Map status string to enum
            status_map = {
                "acknowledged": ReportStatus.ACKNOWLEDGED,
                "in_progress": ReportStatus.IN_PROGRESS,
                "resolved": ReportStatus.RESOLVED,
                "closed": ReportStatus.CLOSED
            }
            
            report.status = status_map.get(new_status, report.status)
            
            if new_status == "resolved":
                report.resolved_at = datetime.now(timezone.utc)
            
            await session.commit()
            
            await query.edit_message_text(
                get_text("status_updated", lang).format(
                    report_id=report_id,
                    status=get_text(f"status_{new_status}", lang)
                )
            )
        else:
            await query.edit_message_text(get_text("operation_failed", lang))


async def show_org_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show organization statistics."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Get user and check permissions
    db_user = await get_or_create_user(user)
    
    if db_user.role not in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    if not db_user.organization_id:
        await update.message.reply_text(get_text("no_organization", lang))
        return
    
    # Get organization statistics
    async with async_session_maker() as session:
        from sqlalchemy import select, func
        
        # Get organization
        org = await session.get(Organization, db_user.organization_id)
        
        if not org:
            await update.message.reply_text(get_text("no_organization", lang))
            return
        
        # Count reports by status
        pending_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.assigned_organization_id == org.id)
            .where(Report.status.in_([ReportStatus.PENDING, ReportStatus.ACKNOWLEDGED]))
        )
        
        in_progress_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.assigned_organization_id == org.id)
            .where(Report.status == ReportStatus.IN_PROGRESS)
        )
        
        # Count this month
        from datetime import datetime, timedelta
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)
        
        month_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.assigned_organization_id == org.id)
            .where(Report.created_at >= month_start)
        )
        
        # Count this week
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        
        week_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.assigned_organization_id == org.id)
            .where(Report.created_at >= week_start)
        )
    
    # Format statistics
    text = get_text("org_stats_title", lang).format(org_name=org.name) + "\n\n"
    text += get_text("stats_total_handled", lang).format(count=org.total_reports_handled) + "\n"
    text += get_text("stats_successful", lang).format(count=org.successful_rescues) + "\n"
    
    if org.average_response_time_minutes:
        text += get_text("stats_avg_response", lang).format(time=int(org.average_response_time_minutes)) + "\n"
    
    text += "\n"
    text += get_text("stats_pending", lang).format(count=pending_count) + "\n"
    text += get_text("stats_in_progress", lang).format(count=in_progress_count) + "\n"
    text += get_text("stats_this_month", lang).format(count=month_count) + "\n"
    text += get_text("stats_this_week", lang).format(count=week_count) + "\n"
    
    await update.message.reply_text(text)


# =============================================================================
# Admin Handlers
# =============================================================================

async def show_admin_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin users management menu."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Check admin permission
    db_user = await get_or_create_user(user)
    if db_user.role != UserRole.SYSTEM_ADMIN:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("search_user", lang),
            callback_data="admin_search_user"
        )],
        [InlineKeyboardButton(
            get_text("view_all_users", lang),
            callback_data="admin_list_users"
        )],
        [InlineKeyboardButton(
            get_text("user_roles_management", lang),
            callback_data="admin_manage_roles"
        )],
        [InlineKeyboardButton(
            get_text("blocked_users", lang),
            callback_data="admin_blocked_users"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_text("users_management_title", lang),
        reply_markup=reply_markup
    )


async def handle_admin_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("search_user", lang)))


async def handle_admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    # Show up to 10 recent users
    async with async_session_maker() as session:
        from sqlalchemy import select, desc
        result = await session.execute(select(User).order_by(desc(User.created_at)).limit(10))
        users = result.scalars().all()
    if not users:
        await query.edit_message_text(get_text("no_users_found", lang))
        return
    text = get_text("recent_users", lang) + "\n\n" + "\n".join([
        f"{u.full_name or u.username or u.email or u.telegram_user_id} — {u.role.value}"
        for u in users
    ])
    await query.edit_message_text(text)


async def handle_admin_manage_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("user_roles_management", lang)))


async def handle_admin_blocked_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("blocked_users", lang)))


async def show_admin_orgs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin organizations management menu."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Check admin permission
    db_user = await get_or_create_user(user)
    if db_user.role != UserRole.SYSTEM_ADMIN:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("pending_org_approvals", lang),
            callback_data="admin_pending_orgs"
        )],
        [InlineKeyboardButton(
            get_text("active_organizations", lang),
            callback_data="admin_active_orgs"
        )],
        [InlineKeyboardButton(
            get_text("add_organization", lang),
            callback_data="admin_add_org"
        )],
        [InlineKeyboardButton(
            get_text("org_performance", lang),
            callback_data="admin_org_performance"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_text("orgs_management_title", lang),
        reply_markup=reply_markup
    )


async def handle_admin_pending_orgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("pending_org_approvals", lang)))


async def handle_admin_active_orgs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    # Show up to 10 active orgs
    async with async_session_maker() as session:
        from sqlalchemy import select, desc
        result = await session.execute(select(Organization).where(Organization.is_active == True).order_by(desc(Organization.created_at)).limit(10))
        orgs = result.scalars().all()
    if not orgs:
        await query.edit_message_text(get_text("no_organizations_found", lang))
        return
    text = get_text("active_organizations", lang) + "\n\n" + "\n".join([
        f"{o.name} — {o.organization_type.value}"
        for o in orgs
    ])
    await query.edit_message_text(text)


async def handle_admin_add_org(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("add_organization", lang)))


async def handle_admin_org_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("org_performance", lang)))


async def show_admin_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin system reports menu."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Check admin permission
    db_user = await get_or_create_user(user)
    if db_user.role != UserRole.SYSTEM_ADMIN:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    # Get system statistics
    async with async_session_maker() as session:
        from sqlalchemy import select, func
        from datetime import datetime, timedelta
        
        # Today's reports
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
        today_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.created_at >= today_start)
        )
        
        # This week
        week_start = datetime.now(timezone.utc) - timedelta(days=7)
        week_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.created_at >= week_start)
        )
        
        # This month
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0)
        month_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.created_at >= month_start)
        )
        
        # Resolved count
        resolved_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.status == ReportStatus.RESOLVED)
            .where(Report.created_at >= month_start)
        )
        
        # Pending count
        pending_count = await session.scalar(
            select(func.count(Report.id))
            .where(Report.status.in_([ReportStatus.PENDING, ReportStatus.ACKNOWLEDGED]))
        )
    
    text = get_text("reports_summary", lang).format(
        today=today_count,
        week=week_count,
        month=month_count,
        resolved=resolved_count,
        pending=pending_count
    )
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("daily_summary", lang),
            callback_data="admin_daily_report"
        )],
        [InlineKeyboardButton(
            get_text("weekly_report", lang),
            callback_data="admin_weekly_report"
        )],
        [InlineKeyboardButton(
            get_text("monthly_statistics", lang),
            callback_data="admin_monthly_stats"
        )],
        [InlineKeyboardButton(
            get_text("export_data", lang),
            callback_data="admin_export_data"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)


async def handle_admin_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("daily_summary", lang)))


async def handle_admin_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("weekly_report", lang)))


async def handle_admin_monthly_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("monthly_statistics", lang)))


async def handle_admin_export_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("export_data", lang)))


async def show_admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin system settings menu."""
    lang = get_user_language(context)
    user = update.effective_user
    
    # Check admin permission
    db_user = await get_or_create_user(user)
    if db_user.role != UserRole.SYSTEM_ADMIN:
        await update.message.reply_text(get_text("permission_denied", lang))
        return
    
    keyboard = [
        [InlineKeyboardButton(
            get_text("maintenance_mode", lang),
            callback_data="admin_maintenance"
        )],
        [InlineKeyboardButton(
            get_text("broadcast_message", lang),
            callback_data="admin_broadcast"
        )],
        [InlineKeyboardButton(
            get_text("system_logs", lang),
            callback_data="admin_logs"
        )],
        [InlineKeyboardButton(
            get_text("backup_restore", lang),
            callback_data="admin_backup"
        )]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_text("system_settings_title", lang),
        reply_markup=reply_markup
    )


async def handle_admin_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("maintenance_mode", lang)))


async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("broadcast_message", lang)))


async def handle_admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("system_logs", lang)))


async def handle_admin_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_user_language(context)
    await query.edit_message_text(get_text("feature_placeholder", lang).format(feature=get_text("backup_restore", lang)))


# =============================================================================
# Language Selection Handlers
# =============================================================================

async def show_language_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show language selection menu."""
    lang = get_user_language(context)
    buttons = [
        [InlineKeyboardButton("🇮🇱 עברית", callback_data="set_lang_he")],
        [InlineKeyboardButton("English", callback_data="set_lang_en")],
        [InlineKeyboardButton("العربية", callback_data="set_lang_ar")],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    prompt = get_text("language_select_title", lang)
    if update.message:
        await update.message.reply_text(prompt, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=reply_markup)


async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback and update preference."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("set_lang_"):
        return
    lang_code = data.replace("set_lang_", "")
    if lang_code not in {"he", "en", "ar"}:
        return
    # Persist preference
    db_user = await get_or_create_user(update.effective_user)
    await set_user_language(db_user.id, lang_code)
    context.user_data[USER_DATA_KEYS["language"]] = lang_code

    lang_names = {"he": "עברית", "en": "English", "ar": "العربية"}
    ack = get_text("language_changed", lang_code).format(language=lang_names.get(lang_code, lang_code))
    try:
        await query.edit_message_text(ack)
    except Exception:
        await query.message.reply_text(ack)

    # Send updated main menu in the selected language
    keyboard = [
        [KeyboardButton(get_text("report_new_incident", lang_code))],
        [
            KeyboardButton(get_text("my_reports", lang_code)),
            KeyboardButton(get_text("help", lang_code)),
        ],
        [
            KeyboardButton(get_text("change_language", lang_code)),
            KeyboardButton(get_text("contact_emergency", lang_code)),
        ],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    welcome = get_text("welcome_message", lang_code).format(
        name=update.effective_user.first_name or "משתמש",
        app_name=settings.APP_NAME,
    )
    await query.message.reply_text(welcome, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# =============================================================================
# Conversation Handler Setup
# =============================================================================

def create_report_conversation_handler() -> ConversationHandler:
    """Create the main report creation conversation handler."""
    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Text(["דיווח חדש", "New Report", "تقرير جديد", "🚨 דווח על חיה"]),
                start_report_creation
            ),
            CommandHandler("report", start_report_creation),
        ],
        states={
            WAITING_FOR_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo_upload),
                MessageHandler(
                    filters.Text(["המשך למיקום", "Continue", "متابعة إلى الموقع"]),
                    request_location
                ),
            ],
            WAITING_FOR_LOCATION: [
                MessageHandler(filters.LOCATION, handle_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location),
            ],
            WAITING_FOR_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description),
            ],
            CONFIRMING_REPORT: [
                CallbackQueryHandler(handle_report_confirmation),
            ],
            SELECTING_URGENCY: [
                CallbackQueryHandler(handle_urgency_selection, pattern="urgency_.*"),
            ],
            SELECTING_ANIMAL_TYPE: [
                CallbackQueryHandler(handle_animal_type_selection, pattern="animal_.*"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            CommandHandler("start", start_command),
        ],
    )


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation."""
    lang = get_user_language(context)
    
    # Clean up user data
    context.user_data.clear()
    
    await update.message.reply_text(
        get_text("conversation_cancelled", lang),
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Show main menu
    await start_command(update, context)
    
    return ConversationHandler.END


# =============================================================================
# Application Builder
# =============================================================================

def create_bot_application() -> Application:
    """Create and configure the Telegram bot application."""
    
    # Build application
    application = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("language", show_language_menu))
    
    # Dev-only: promote current user to system admin and attach to first org
    async def dev_promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if settings.ENVIRONMENT == "production":
            await update.message.reply_text("פקודה אינה זמינה בפרודקשן")
            return
        user = update.effective_user
        db_user = await get_or_create_user(user)
        async with async_session_maker() as session:
            from sqlalchemy import select
            # Ensure at least one org exists
            result = await session.execute(select(Organization).limit(1))
            org = result.scalar_one_or_none()
            if not org:
                org = Organization(name="Org for Admin", organization_type=OrganizationType.RESCUE_ORG, is_active=True)
                session.add(org)
                await session.flush()
            # Promote
            db_user = await session.get(User, db_user.id)
            db_user.role = UserRole.SYSTEM_ADMIN
            db_user.organization_id = org.id
            await session.commit()
        await update.message.reply_text("הוקצו הרשאות אדמין מערכת + שיוך לארגון ✅. שלח /start לרענון התפריט.")

    application.add_handler(CommandHandler("dev_promote", dev_promote))
    
    # Add conversation handler for report creation
    report_handler = create_report_conversation_handler()
    application.add_handler(report_handler)
    
    # Add callback handlers for various actions
    application.add_handler(CallbackQueryHandler(
        handle_report_tracking, pattern="track_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_report_sharing, pattern="share_.*"  
    ))
    application.add_handler(CallbackQueryHandler(
        handle_language_selection, pattern="^set_lang_.*$"
    ))
    
    # User Settings handlers
    application.add_handler(CallbackQueryHandler(
        handle_service_area_settings, pattern="settings_service_area"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_notification_settings, pattern="settings_notifications"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_contact_details_settings, pattern="settings_contact"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_service_radius_selection, pattern="service_radius_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_notification_category, pattern="notif_category_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_notification_toggle, pattern="toggle_notif_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_quiet_hours_settings, pattern="notif_quiet_hours"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_quiet_hours_set, pattern="quiet_hours_set"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_quiet_hours_disable, pattern="quiet_hours_disable"
    ))
    application.add_handler(CallbackQueryHandler(
        show_user_settings_menu, pattern="settings_menu"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_contact_update_phone, pattern="contact_update_phone"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_contact_update_email, pattern="contact_update_email"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_contact_emergency, pattern="contact_emergency"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_settings_back, pattern="settings_back"
    ))
    
    # Organization handlers
    application.add_handler(CallbackQueryHandler(
        handle_org_report_action, pattern="org_report_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_org_report_details, pattern="org_details_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_org_acknowledge_report, pattern="org_ack_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_org_update_status, pattern="org_status_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_set_report_status, pattern="set_status_.*"
    ))
    application.add_handler(CallbackQueryHandler(
        handle_org_reports_list, pattern="org_reports_list"
    ))
    
    # Add message handlers
    application.add_handler(MessageHandler(
        filters.Text(["עזרה", "Help", "مساعدة"]), 
        help_command
    ))
    application.add_handler(MessageHandler(
        filters.Text(["הדיווחים שלי", "My Reports", "تقاريري"]),
        status_command
    ))
    application.add_handler(MessageHandler(
        filters.Text(["שינוי שפה", "Change Language", "تغيير اللغة"]),
        show_language_menu
    ))
    application.add_handler(MessageHandler(
        filters.Text(["⚙️ הגדרות", "Settings"]),
        show_user_settings_menu
    ))
    
    # Organization message handlers
    application.add_handler(MessageHandler(
        filters.Text(["📥 דיווחים שהוקצו לי"]),
        show_assigned_reports
    ))
    application.add_handler(MessageHandler(
        filters.Text(["📈 סטטיסטיקות הארגון"]),
        show_org_statistics
    ))
    
    # Admin message handlers
    application.add_handler(MessageHandler(
        filters.Text(["👥 ניהול משתמשים"]),
        show_admin_users_menu
    ))
    application.add_handler(MessageHandler(
        filters.Text(["🏢 ניהול ארגונים"]),
        show_admin_orgs_menu
    ))
    application.add_handler(MessageHandler(
        filters.Text(["📊 דוחות מערכת"]),
        show_admin_reports_menu
    ))
    application.add_handler(MessageHandler(
        filters.Text(["🔧 הגדרות מערכת"]),
        show_admin_settings_menu
    ))

    # Admin callback handlers
    application.add_handler(CallbackQueryHandler(handle_admin_search_user, pattern="admin_search_user"))
    application.add_handler(CallbackQueryHandler(handle_admin_list_users, pattern="admin_list_users"))
    application.add_handler(CallbackQueryHandler(handle_admin_manage_roles, pattern="admin_manage_roles"))
    application.add_handler(CallbackQueryHandler(handle_admin_blocked_users, pattern="admin_blocked_users"))
    application.add_handler(CallbackQueryHandler(handle_admin_pending_orgs, pattern="admin_pending_orgs"))
    application.add_handler(CallbackQueryHandler(handle_admin_active_orgs, pattern="admin_active_orgs"))
    application.add_handler(CallbackQueryHandler(handle_admin_add_org, pattern="admin_add_org"))
    application.add_handler(CallbackQueryHandler(handle_admin_org_performance, pattern="admin_org_performance"))
    application.add_handler(CallbackQueryHandler(handle_admin_daily_report, pattern="admin_daily_report"))
    application.add_handler(CallbackQueryHandler(handle_admin_weekly_report, pattern="admin_weekly_report"))
    application.add_handler(CallbackQueryHandler(handle_admin_monthly_stats, pattern="admin_monthly_stats"))
    application.add_handler(CallbackQueryHandler(handle_admin_export_data, pattern="admin_export_data"))
    application.add_handler(CallbackQueryHandler(handle_admin_maintenance, pattern="admin_maintenance"))
    application.add_handler(CallbackQueryHandler(handle_admin_broadcast, pattern="admin_broadcast"))
    application.add_handler(CallbackQueryHandler(handle_admin_logs, pattern="admin_logs"))
    application.add_handler(CallbackQueryHandler(handle_admin_backup, pattern="admin_backup"))
    
    # Handle location messages for service area setup
    application.add_handler(MessageHandler(
        filters.LOCATION,
        handle_service_area_location
    ))
    # Handle text inputs for quiet hours and contact details
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_quiet_hours_input
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_phone_input
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_email_input
    ))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    return application


# =============================================================================
# Utility Handlers
# =============================================================================

async def handle_report_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle report tracking callback."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    public_id = query.data.replace("track_", "")
    
    # Get report status
    async with async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Report).where(Report.public_id == public_id)
        )
        report = result.scalar_one_or_none()
    
    if not report:
        await query.message.reply_text(
            get_text("report_not_found", lang)
        )
        return
    
    # Format status message
    status_text = get_text("report_status_details", lang).format(
        report_id=report.public_id,
        status=get_text(f"status_{report.status.value}", lang),
        created=report.created_at.strftime("%d/%m/%Y %H:%M"),
        location=report.city or get_text("location_unknown", lang)
    )
    
    await query.message.reply_text(status_text, parse_mode=ParseMode.HTML)


async def handle_report_sharing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle report sharing callback."""
    query = update.callback_query
    await query.answer()
    
    lang = get_user_language(context)
    public_id = query.data.replace("share_", "")
    
    share_url = f"https://t.me/{context.bot.username}?start=report_{public_id}"
    share_text = get_text("share_report_text", lang).format(
        report_id=public_id,
        url=share_url
    )
    
    await query.message.reply_text(share_text, parse_mode=ParseMode.HTML)


async def handle_settings_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return from settings inline menu back to main keyboard menu."""
    query = update.callback_query
    await query.answer()
    try:
        await start_command(update, context)
    except Exception:
        pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bot errors."""
    logger.error("Bot error occurred", error=str(context.error), exc_info=True)
    
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "אירעה שגיאה. נסה שוב מאוחר יותר."
            )
        except Exception:
            pass  # Don't fail on error message failures


# =============================================================================
# Bot Instance
# =============================================================================

# Create global bot application
bot_application = create_bot_application()
bot = bot_application.bot


async def initialize_bot() -> None:
    """Initialize the bot and set up webhook if configured."""
    # Ensure Application is initialized and started so process_update works in webhook mode
    try:
        await bot_application.initialize()
    except Exception:
        # It might already be initialized
        pass
    try:
        await bot_application.start()
    except Exception:
        # It might already be started
        pass

    if settings.WEBHOOK_HOST and settings.TELEGRAM_WEBHOOK_URL:
        await bot.set_webhook(
            url=settings.TELEGRAM_WEBHOOK_URL,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        logger.info("Webhook set up", url=settings.TELEGRAM_WEBHOOK_URL)
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook disabled, using polling")


# =============================================================================
# Export
# =============================================================================

_polling_task = None


async def start_polling_if_needed() -> bool:
    """Start Telegram polling in background when webhook is not configured.

    Returns True if polling was started (or already running), False if webhook mode.
    """
    # If webhook configured, do not start polling
    if settings.WEBHOOK_HOST and settings.TELEGRAM_WEBHOOK_URL:
        return False

    global _polling_task
    # Avoid double start
    if _polling_task and not _polling_task.done():
        return True

    # Ensure application is initialized and started before polling
    try:
        await bot_application.initialize()
    except Exception:
        # It's OK if already initialized
        pass
    await bot_application.start()

    # Acquire distributed polling lock to ensure single getUpdates instance
    lock_key = settings.POLLING_LOCK_KEY
    lease = settings.LOCK_LEASE_SECONDS
    hb_interval = settings.LOCK_HEARTBEAT_INTERVAL

    async def _heartbeat(identifier: str):
        try:
            while _polling_task and not _polling_task.done():
                # Renew lock only if owned by this identifier
                lua = """
                local k=KEYS[1]
                local id=ARGV[1]
                local ttl=tonumber(ARGV[2])
                if redis.call('GET', k) == id then
                    return redis.call('EXPIRE', k, ttl)
                else
                    return 0
                end
                """
                try:
                    res = await redis_client.eval(lua, 1, lock_key, identifier, lease)
                except Exception:
                    res = 0
                if not res:
                    # Lock lost → stop polling immediately
                    logger.warning("Polling lock lost, stopping polling")
                    try:
                        if getattr(bot_application, "updater", None):
                            await bot_application.updater.stop()
                    except Exception:
                        pass
                    break
                await asyncio.sleep(hb_interval)
        except Exception:
            pass

    async def _acquire_lock(max_wait: int | None) -> str | None:
        start = asyncio.get_event_loop().time()
        identifier = f"{id(bot_application)}:{start}"
        while True:
            try:
                acquired = await redis_client.set(lock_key, identifier, nx=True, ex=lease)
            except Exception:
                acquired = False
            if acquired:
                return identifier
            if not settings.LOCK_WAIT_FOR_ACQUIRE:
                # Passive wait with random backoff
                import random
                wait_min = int(os.getenv("LOCK_WAIT_MIN_SECONDS", "15"))
                wait_max = int(os.getenv("LOCK_WAIT_MAX_SECONDS", "45"))
                delay = random.randint(wait_min, max(wait_min, wait_max))
                logger.info("Polling lock busy; sleeping", seconds=delay)
                await asyncio.sleep(delay)
            else:
                if max_wait and (asyncio.get_event_loop().time() - start) > max_wait:
                    return None
                await asyncio.sleep(2)

    import asyncio, os as _os
    import os
    max_wait = settings.LOCK_ACQUIRE_MAX_WAIT if settings.LOCK_WAIT_FOR_ACQUIRE else 0
    lock_id = await _acquire_lock(max_wait if max_wait and max_wait > 0 else None)
    if lock_id is None:
        logger.info("Polling lock not acquired within limit; skipping polling")
        return False

    # Run polling without blocking the event loop
    import asyncio as _asyncio
    _polling_task = _asyncio.create_task(bot_application.updater.start_polling())
    # Start heartbeat renewer
    _asyncio.create_task(_heartbeat(lock_id))

    logger.info("📡 Telegram polling started (with distributed lock)")
    return True


async def shutdown_bot() -> None:
    """Gracefully stop polling and shutdown the bot application."""
    global _polling_task
    try:
        if getattr(bot_application, "updater", None):
            await bot_application.updater.stop()
    except Exception:
        pass
    try:
        await bot_application.stop()
    except Exception:
        pass
    try:
        await bot_application.shutdown()
    except Exception:
        pass
    _polling_task = None


__all__ = [
    "bot_application",
    "bot",
    "initialize_bot",
    "create_bot_application",
    "start_polling_if_needed",
    "shutdown_bot",
]
