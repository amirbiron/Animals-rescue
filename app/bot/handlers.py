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
from app.models.database import async_session_maker, User, Report, ReportFile
from app.models.database import AnimalType, UrgencyLevel, ReportStatus, UserRole
from app.services.nlp import NLPService
from app.services.geocoding import GeocodingService
from app.services.file_storage import FileStorageService
from app.workers.jobs import process_new_report
from app.core.i18n import get_text, detect_language, set_user_language

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
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user.id)
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
        
        # Detect and set user language
        detected_lang = detect_language(update.message.text) or user.language_code or "he"
        await set_user_language(db_user.id, detected_lang)
        context.user_data[USER_DATA_KEYS["language"]] = detected_lang
        
        # Show typing indicator
        await set_typing_action(update, context)
        
        # Welcome message
        welcome_text = get_text("welcome_message", detected_lang).format(
            name=user.first_name or "משתמש",
            app_name=settings.APP_NAME
        )
        
        # Main menu keyboard
        keyboard = [
            [KeyboardButton(get_text("report_new_incident", detected_lang))],
            [
                KeyboardButton(get_text("my_reports", detected_lang)),
                KeyboardButton(get_text("help", detected_lang))
            ],
            [
                KeyboardButton(get_text("change_language", detected_lang)),
                KeyboardButton(get_text("contact_emergency", detected_lang))
            ]
        ]
        
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=False
        )
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
    except RateLimitExceeded as e:
        await update.message.reply_text(
            get_text("rate_limit_exceeded", get_user_language(context))
        )
        
    except Exception as e:
        logger.error("Error in start command", error=str(e), exc_info=True)
        await update.message.reply_text(
            get_text("error_generic", get_user_language(context))
        )


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
    
    await update.message.reply_text(
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
        
        if update.message.location:
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
                location_data.update(address_info)
            except Exception as e:
                logger.warning("Reverse geocoding failed", error=str(e))
                location_data["address"] = get_text("address_unavailable", lang)
                location_data["city"] = None
            
        elif update.message.text:
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
                geocode_result = await geocoding_service.geocode(address)
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
            address=location_data.get("address", get_text("coordinates_only", lang)),
            city=location_data.get("city", get_text("unknown_city", lang))
        )
        
        await update.message.reply_text(
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
    description = update.message.text.strip()
    
    if not description or len(description) < 10:
        await update.message.reply_text(
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
        await update.message.reply_text(
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
        
        # Queue background jobs
        process_new_report.delay(str(report.id))
        
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
            await update.message.reply_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        
        # Clean up user data
        context.user_data.clear()
        
        # Show main menu again
        await asyncio.sleep(2)  # Brief pause
        await start_command(update, context)
        
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
            await update.message.reply_text(error_text)
        
        return ConversationHandler.END


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
    
    # Add message handlers
    application.add_handler(MessageHandler(
        filters.Text(["עזרה", "Help", "مساعدة"]), 
        help_command
    ))
    application.add_handler(MessageHandler(
        filters.Text(["הדיווחים שלי", "My Reports", "تقاريري"]),
        status_command
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
