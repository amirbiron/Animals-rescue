"""
Internationalization (i18n) support for the Animal Rescue Bot system.

This module handles multiple languages and provides translation services
for the entire application including bot messages, API responses, and notifications.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from functools import lru_cache

import structlog
from app.core.config import settings
from app.core.cache import redis_client

logger = structlog.get_logger(__name__)

# Language configuration
DEFAULT_LANGUAGE = settings.DEFAULT_LANGUAGE
SUPPORTED_LANGUAGES = settings.SUPPORTED_LANGUAGES
FALLBACK_LANGUAGE = "en"

# Cache settings
TRANSLATION_CACHE_TTL = 3600  # 1 hour
USER_LANGUAGE_CACHE_TTL = 86400  # 24 hours

# Language detection patterns
LANGUAGE_PATTERNS = {
    "he": [
        r"[\u0590-\u05FF]",  # Hebrew block
        r"[\uFB1D-\uFB4F]",  # Hebrew presentation forms
    ],
    "ar": [
        r"[\u0600-\u06FF]",  # Arabic block
        r"[\u0750-\u077F]",  # Arabic supplement
        r"[\uFE70-\uFEFF]",  # Arabic presentation forms
    ]
}

class TranslationLoader:
    """Loads and manages translation files."""
    
    def __init__(self, translations_dir: str = "app/translations"):
        self.translations_dir = Path(translations_dir)
        self._translations: Dict[str, Dict[str, str]] = {}
        self._loaded_languages: set = set()
    
    def load_language(self, language: str) -> Dict[str, str]:
        """Load translations for a specific language."""
        if language in self._loaded_languages:
            return self._translations.get(language, {})
        
        translation_file = self.translations_dir / f"{language}.json"
        
        if not translation_file.exists():
            # Log once per language at debug level to reduce noise
            logger.debug(
                "Translation file not found",
                language=language,
                file_path=str(translation_file)
            )
            self._translations[language] = {}
            self._loaded_languages.add(language)
            return {}
        
        try:
            with open(translation_file, "r", encoding="utf-8") as f:
                translations = json.load(f)
            
            self._translations[language] = translations
            self._loaded_languages.add(language)
            
            logger.info(
                "Loaded translations",
                language=language,
                count=len(translations)
            )
            
            return translations
        
        except Exception as e:
            logger.error(
                "Failed to load translation file",
                language=language,
                file_path=str(translation_file),
                error=str(e)
            )
            self._translations[language] = {}
            self._loaded_languages.add(language)
            return {}
    
    def get_translation(self, language: str, key: str) -> Optional[str]:
        """Get a specific translation."""
        if language not in self._loaded_languages:
            self.load_language(language)
        
        return self._translations.get(language, {}).get(key)
    
    def reload_all(self) -> None:
        """Reload all translation files."""
        self._translations.clear()
        self._loaded_languages.clear()
        
        for lang in SUPPORTED_LANGUAGES:
            self.load_language(lang)


# Global translation loader instance
_translation_loader = TranslationLoader()


class I18nService:
    """Main internationalization service."""
    
    def __init__(self):
        self.loader = _translation_loader
        
        # Load all supported languages at startup
        for lang in SUPPORTED_LANGUAGES:
            self.loader.load_language(lang)
    
    async def get_user_language(self, user_id: Union[str, int]) -> str:
        """Get user's preferred language from cache."""
        cache_key = f"user_language:{user_id}"
        
        try:
            cached_lang = await redis_client.get(cache_key)
            if cached_lang:
                # redis client is configured with decode_responses=True and returns str
                lang = cached_lang if isinstance(cached_lang, str) else cached_lang.decode('utf-8', errors='ignore')
                if lang in SUPPORTED_LANGUAGES:
                    return lang
        except Exception as e:
            logger.warning(
                "Failed to get user language from cache",
                user_id=user_id,
                error=str(e)
            )
        
        return DEFAULT_LANGUAGE
    
    async def set_user_language(
        self,
        user_id: Union[str, int],
        language: str
    ) -> bool:
        """Set user's preferred language in cache."""
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(
                "Attempted to set unsupported language",
                user_id=user_id,
                language=language,
                supported=SUPPORTED_LANGUAGES
            )
            return False
        
        cache_key = f"user_language:{user_id}"
        
        try:
            await redis_client.setex(
                cache_key,
                USER_LANGUAGE_CACHE_TTL,
                language
            )
            
            logger.info(
                "Set user language",
                user_id=user_id,
                language=language
            )
            
            return True
        
        except Exception as e:
            logger.error(
                "Failed to set user language in cache",
                user_id=user_id,
                language=language,
                error=str(e)
            )
            return False
    
    def detect_language(self, text: str) -> str:
        """Detect language from text content."""
        if not text or not text.strip():
            return DEFAULT_LANGUAGE
        
        # Clean text for analysis
        text = text.strip()
        
        # Check for language-specific characters
        for lang, patterns in LANGUAGE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text):
                    # Additional validation - ensure significant amount of text
                    # matches the pattern
                    matches = len(re.findall(pattern, text))
                    if matches >= min(3, len(text) * 0.1):  # At least 3 chars or 10%
                        return lang
        
        # Default to English if no specific patterns found
        # and it's not obviously Hebrew/Arabic
        if any(char.isascii() and char.isalpha() for char in text):
            return "en"
        
        return DEFAULT_LANGUAGE
    
    def get_text(
        self,
        key: str,
        language: Optional[str] = None,
        user_id: Optional[Union[str, int]] = None,
        **kwargs
    ) -> str:
        """
        Get translated text for a key.
        
        Args:
            key: Translation key
            language: Target language (if not provided, will try to detect)
            user_id: User ID to get preferred language (async context required)
            **kwargs: Variables to substitute in the translation
        
        Returns:
            Translated text with variables substituted
        """
        # Determine language
        if not language:
            language = DEFAULT_LANGUAGE
        
        # Get translation with fallback chain
        text = self._get_translation_with_fallback(key, language)
        
        # Substitute variables
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError) as e:
                logger.warning(
                    "Failed to substitute variables in translation",
                    key=key,
                    language=language,
                    variables=kwargs,
                    error=str(e)
                )
                # Return text without substitution
        
        return text
    
    def _get_translation_with_fallback(self, key: str, language: str) -> str:
        """Get translation with fallback to other languages."""
        # Try requested language
        if language in SUPPORTED_LANGUAGES:
            translation = self.loader.get_translation(language, key)
            if translation:
                return translation
        
        # Try fallback language
        if language != FALLBACK_LANGUAGE:
            translation = self.loader.get_translation(FALLBACK_LANGUAGE, key)
            if translation:
                return translation
        
        # Try default language
        if language != DEFAULT_LANGUAGE and FALLBACK_LANGUAGE != DEFAULT_LANGUAGE:
            translation = self.loader.get_translation(DEFAULT_LANGUAGE, key)
            if translation:
                return translation
        
        # Return key as fallback
        # Avoid noisy warnings on every missing key, use debug instead
        logger.debug(
            "Translation not found",
            key=key,
            language=language,
            fallback_attempted=True
        )
        
        return f"[{key}]"  # Indicate missing translation
    
    async def get_text_async(
        self,
        key: str,
        user_id: Optional[Union[str, int]] = None,
        language: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Get translated text with async user language lookup.
        
        Args:
            key: Translation key
            user_id: User ID to get preferred language from
            language: Override language (if provided, user_id is ignored)
            **kwargs: Variables to substitute in the translation
        """
        # Get language
        if language:
            target_language = language
        elif user_id:
            target_language = await self.get_user_language(user_id)
        else:
            target_language = DEFAULT_LANGUAGE
        
        return self.get_text(key, target_language, **kwargs)
    
    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return SUPPORTED_LANGUAGES.copy()
    
    def is_supported_language(self, language: str) -> bool:
        """Check if a language is supported."""
        return language in SUPPORTED_LANGUAGES
    
    def get_language_name(self, language: str) -> str:
        """Get human-readable language name."""
        names = {
            "he": "עברית",
            "ar": "العربية", 
            "en": "English"
        }
        return names.get(language, language)
    
    def get_text_direction(self, language: str) -> str:
        """Get text direction for a language."""
        rtl_languages = {"he", "ar"}
        return "rtl" if language in rtl_languages else "ltr"
    
    def reload_translations(self) -> None:
        """Reload all translation files."""
        self.loader.reload_all()
        logger.info("Reloaded all translations")


# Global i18n service instance
_i18n_service = I18nService()


# Convenience functions for backward compatibility
def detect_language(text: str) -> str:
    """Detect language from text."""
    return _i18n_service.detect_language(text)


def get_text(
    key: str,
    language: Optional[str] = None,
    **kwargs
) -> str:
    """Get translated text."""
    return _i18n_service.get_text(key, language, **kwargs)


async def get_text_async(
    key: str,
    user_id: Optional[Union[str, int]] = None,
    language: Optional[str] = None,
    **kwargs
) -> str:
    """Get translated text with async user language lookup."""
    return await _i18n_service.get_text_async(key, user_id, language, **kwargs)


async def set_user_language(
    user_id: Union[str, int],
    language: str
) -> bool:
    """Set user's preferred language."""
    return await _i18n_service.set_user_language(user_id, language)


async def get_user_language(user_id: Union[str, int]) -> str:
    """Get user's preferred language."""
    return await _i18n_service.get_user_language(user_id)


def get_supported_languages() -> List[str]:
    """Get supported languages."""
    return _i18n_service.get_supported_languages()


def is_supported_language(language: str) -> bool:
    """Check if language is supported."""
    return _i18n_service.is_supported_language(language)


def get_language_name(language: str) -> str:
    """Get human-readable language name."""
    return _i18n_service.get_language_name(language)


def get_text_direction(language: str) -> str:
    """Get text direction for language."""
    return _i18n_service.get_text_direction(language)


def reload_translations() -> None:
    """Reload all translation files."""
    _i18n_service.reload_translations()


# Translation helpers for common patterns
class BotMessages:
    """Predefined keys for bot messages."""
    
    # Start and help
    START_MESSAGE = "bot.start_message"
    HELP_MESSAGE = "bot.help_message" 
    COMMANDS_LIST = "bot.commands_list"
    
    # Report creation flow
    REPORT_START = "bot.report.start"
    REPORT_PHOTO_REQUEST = "bot.report.photo_request"
    REPORT_LOCATION_REQUEST = "bot.report.location_request"
    REPORT_DESCRIPTION_REQUEST = "bot.report.description_request"
    REPORT_URGENCY_SELECT = "bot.report.urgency_select"
    REPORT_ANIMAL_TYPE_SELECT = "bot.report.animal_type_select"
    REPORT_CONFIRMATION = "bot.report.confirmation"
    REPORT_SUBMITTED = "bot.report.submitted"
    REPORT_CANCELLED = "bot.report.cancelled"
    
    # Errors
    ERROR_GENERAL = "bot.error.general"
    ERROR_PHOTO_REQUIRED = "bot.error.photo_required"
    ERROR_LOCATION_REQUIRED = "bot.error.location_required"
    ERROR_DESCRIPTION_TOO_SHORT = "bot.error.description_too_short"
    ERROR_RATE_LIMIT = "bot.error.rate_limit"
    
    # Status messages
    STATUS_USER_REPORTS = "bot.status.user_reports"
    STATUS_NO_REPORTS = "bot.status.no_reports"
    
    # Language selection
    LANGUAGE_CHANGED = "bot.language.changed"
    LANGUAGE_SELECT = "bot.language.select"


class APIMessages:
    """Predefined keys for API messages."""
    
    # General
    SUCCESS = "api.success"
    ERROR = "api.error"
    NOT_FOUND = "api.not_found"
    PERMISSION_DENIED = "api.permission_denied"
    VALIDATION_ERROR = "api.validation_error"
    
    # Reports
    REPORT_CREATED = "api.report.created"
    REPORT_UPDATED = "api.report.updated"
    REPORT_DELETED = "api.report.deleted"
    REPORT_NOT_FOUND = "api.report.not_found"
    
    # Files
    FILE_UPLOADED = "api.file.uploaded"
    FILE_TOO_LARGE = "api.file.too_large"
    FILE_TYPE_UNSUPPORTED = "api.file.type_unsupported"


class AlertMessages:
    """Predefined keys for alert messages."""
    
    # New report alerts
    NEW_REPORT_SUBJECT = "alert.new_report.subject"
    NEW_REPORT_BODY = "alert.new_report.body"
    
    # Status updates
    STATUS_UPDATE_SUBJECT = "alert.status_update.subject"
    STATUS_UPDATE_BODY = "alert.status_update.body"
    
    # Reminders
    FOLLOW_UP_REMINDER = "alert.follow_up_reminder"
    URGENT_REMINDER = "alert.urgent_reminder"


# Template translations that should exist in translation files
REQUIRED_TRANSLATIONS = {
    # Bot messages
    BotMessages.START_MESSAGE: "Welcome to Animal Rescue Bot! Send /help for commands.",
    BotMessages.HELP_MESSAGE: "Use /new_report to create a new rescue report.",
    BotMessages.ERROR_GENERAL: "An error occurred. Please try again.",
    
    # API messages  
    APIMessages.SUCCESS: "Operation completed successfully",
    APIMessages.ERROR: "An error occurred",
    APIMessages.NOT_FOUND: "Resource not found",
    
    # Alert messages
    AlertMessages.NEW_REPORT_SUBJECT: "New Animal Rescue Report",
    AlertMessages.NEW_REPORT_BODY: "A new animal rescue report has been submitted."
}


def create_default_translations() -> Dict[str, str]:
    """Create default English translations."""
    return REQUIRED_TRANSLATIONS.copy()


# Initialize translations on import
@lru_cache(maxsize=1)
def _initialize_translations():
    """Initialize translation system on first import."""
    try:
        # Ensure translations directory exists
        translations_dir = Path("app/translations")
        translations_dir.mkdir(exist_ok=True)
        
        # Create default English translations if they don't exist
        en_file = translations_dir / "en.json"
        if not en_file.exists():
            with open(en_file, "w", encoding="utf-8") as f:
                json.dump(create_default_translations(), f, indent=2, ensure_ascii=False)
            
            logger.info("Created default English translations")
        
        # Load all translations
        _i18n_service.reload_translations()
        
    except Exception as e:
        logger.error("Failed to initialize translations", error=str(e))


# Initialize on import
_initialize_translations()
