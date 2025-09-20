"""
Configuration and Settings Management
הגדרות והקונפיגורציה של המערכת

This module handles all application configuration using Pydantic Settings
with support for environment variables and 12-Factor App principles.
"""

import logging
import secrets
from functools import lru_cache
import os
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings

# =============================================================================
# Base Directories
# =============================================================================

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()

# =============================================================================
# Core Application Settings
# =============================================================================

class Settings(BaseSettings):
    """
    Application settings with environment variable support.
    
    All settings can be overridden via environment variables.
    For nested settings, use double underscore: DATABASE__HOST=localhost
    """
    
    # =========================================================================
    # Application Core
    # =========================================================================
    
    # Application metadata
    APP_NAME: str = "Animal Rescue Bot"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "בוט הצלת בעלי חיים - דיווח והתראות מהיר"
    
    # Environment configuration
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = "development"
    DEBUG: bool = Field(default=False, description="Debug mode")
    
    # Security
    SECRET_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="Secret key for JWT and other cryptographic operations"
    )
    
    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = Field(
        default=["*"],  # In production, replace with specific origins
        description="Allowed CORS origins"
    )
    
    # =========================================================================
    # Database Configuration (PostgreSQL)
    # =========================================================================
    
    # PostgreSQL connection parameters
    POSTGRES_HOST: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL port")
    POSTGRES_DB: str = Field(default="animal_rescue", description="Database name")
    POSTGRES_USER: str = Field(default="postgres", description="Database user")
    POSTGRES_PASSWORD: str = Field(default="postgres", description="Database password")
    
    # Connection pool settings
    DATABASE_POOL_SIZE: int = Field(default=10, description="Database connection pool size")
    DATABASE_MAX_OVERFLOW: int = Field(default=20, description="Max overflow connections")
    DATABASE_POOL_TIMEOUT: int = Field(default=30, description="Pool timeout in seconds")
    DATABASE_ECHO: bool = Field(default=False, description="Echo SQL queries")
    
    # Computed database URL (will be set by model_validator)
    DATABASE_URL: Optional[str] = None
    
    @model_validator(mode='after')
    def assemble_database_url(self) -> 'Settings':
        # Respect explicit DATABASE_URL from environment if provided
        url = self.DATABASE_URL
        if not url:
            url = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        # Normalize common URL schemes to SQLAlchemy async driver
        if isinstance(url, str):
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        object.__setattr__(self, "DATABASE_URL", url)
        return self
    
    # =========================================================================
    # Redis Configuration
    # =========================================================================
    
    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_DB: int = Field(default=0, description="Redis database number")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis password")
    REDIS_MAX_CONNECTIONS: int = Field(default=20, description="Redis connection pool size")
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Full Redis URL (redis:// or rediss://) for main cache",
    )
    REDIS_QUEUE_URL: Optional[str] = Field(
        default=None,
        description="Redis URL for RQ job queue (uses DB 1)",
    )

    @model_validator(mode='after')
    def assemble_redis_urls(self) -> 'Settings':
        """Assemble Redis URLs if not provided explicitly via env variables."""
        # Prefer fully specified REDIS_URL; also support providers that expose REDIS_TLS_URL
        if not self.REDIS_URL:
            tls_url = os.getenv("REDIS_TLS_URL")
            if tls_url:
                object.__setattr__(self, "REDIS_URL", tls_url)
            else:
                auth_part = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
                url = f"redis://{auth_part}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
                object.__setattr__(self, "REDIS_URL", url)

        # Derive REDIS_QUEUE_URL from REDIS_URL when not explicitly set, keeping same host/auth and switching DB to 1
        if not self.REDIS_QUEUE_URL:
            try:
                parsed = urlparse(self.REDIS_URL)
                # Replace path with /1 (DB index)
                new_path = "/1"
                queue_url = urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    new_path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                ))
            except Exception:
                # Fallback to host/port composition
                auth_part = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
                queue_url = f"redis://{auth_part}{self.REDIS_HOST}:{self.REDIS_PORT}/1"
            object.__setattr__(self, "REDIS_QUEUE_URL", queue_url)
        return self
    
    # =========================================================================
    # Telegram Bot Configuration
    # =========================================================================
    
    # Bot credentials
    TELEGRAM_BOT_TOKEN: str = Field(description="Telegram bot token from @BotFather")
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Webhook secret token for security"
    )
    
    # Webhook configuration
    WEBHOOK_HOST: Optional[str] = Field(
        default=None,
        description="Public host for webhook (e.g., https://your-app.com)"
    )
    WEBHOOK_PATH: str = Field(
        default="/telegram/webhook",
        description="Webhook endpoint path"
    )
    
    @property
    def TELEGRAM_WEBHOOK_URL(self) -> Optional[str]:
        """Complete webhook URL."""
        if self.WEBHOOK_HOST:
            return f"{self.WEBHOOK_HOST.rstrip('/')}{self.WEBHOOK_PATH}"
        return None
    
    # Rate limiting for bot
    TELEGRAM_RATE_LIMIT_MESSAGES: int = Field(default=20, description="Messages per minute per user")
    TELEGRAM_RATE_LIMIT_WINDOW: int = Field(default=60, description="Rate limit window in seconds")

    # Polling lock (to avoid multiple getUpdates instances)
    POLLING_LOCK_KEY: str = Field(
        default="bot:polling_lock",
        description="Redis key for distributed polling lock"
    )
    LOCK_LEASE_SECONDS: int = Field(
        default=60,
        description="Lease duration for polling lock (seconds)"
    )
    LOCK_HEARTBEAT_INTERVAL: Optional[int] = Field(
        default=None,
        description="Heartbeat interval to renew polling lock (seconds)"
    )
    LOCK_WAIT_FOR_ACQUIRE: bool = Field(
        default=False,
        description="Whether to wait for lock acquisition at startup"
    )
    LOCK_ACQUIRE_MAX_WAIT: int = Field(
        default=0,
        description="Max seconds to wait for lock when waiting (0 = unlimited)"
    )
    
    # =========================================================================
    # External APIs Configuration
    # =========================================================================
    
    # Google APIs
    GOOGLE_PLACES_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Places API key"
    )
    GOOGLE_GEOCODING_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Geocoding API key (can be same as Places)"
    )
    
    # API rate limits
    GOOGLE_API_RATE_LIMIT: int = Field(default=10, description="Google API requests per second")
    GOOGLE_API_QUOTA_DAILY: int = Field(default=1000, description="Daily API quota limit")
    
    # =========================================================================
    # File Storage Configuration
    # =========================================================================
    
    # File storage backend
    STORAGE_BACKEND: Literal["local", "s3", "r2"] = Field(default="local")
    
    # Local storage
    UPLOAD_DIR: Path = Field(default=PROJECT_ROOT / "uploads")
    MAX_FILE_SIZE_MB: int = Field(default=10, description="Max file size in MB")
    ALLOWED_FILE_TYPES: List[str] = Field(
        default=["image/jpeg", "image/png", "image/webp"],
        description="Allowed MIME types for uploads"
    )
    
    # S3/R2 Configuration (Cloudflare R2)
    S3_ENDPOINT_URL: Optional[str] = Field(default=None, description="S3/R2 endpoint URL")
    S3_ACCESS_KEY_ID: Optional[str] = Field(default=None)
    S3_SECRET_ACCESS_KEY: Optional[str] = Field(default=None)
    S3_BUCKET_NAME: Optional[str] = Field(default=None)
    S3_REGION: str = Field(default="auto", description="S3 region")
    
    # File lifecycle
    FILE_CLEANUP_DAYS: int = Field(default=180, description="Days before cleaning up old files")
    
    # =========================================================================
    # Email Configuration
    # =========================================================================
    
    # SMTP settings
    SMTP_HOST: Optional[str] = Field(default=None)
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: Optional[EmailStr] = Field(default=None)
    SMTP_PASSWORD: Optional[str] = Field(default=None)
    SMTP_TLS: bool = Field(default=True)
    
    # Email addresses
    EMAILS_FROM_EMAIL: Optional[EmailStr] = Field(default=None)
    EMAILS_FROM_NAME: str = Field(default="Animal Rescue Bot")

    # =========================================================================
    # SMS / WhatsApp Configuration (Twilio)
    # =========================================================================
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None, description="Twilio Account SID")
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None, description="Twilio Auth Token")
    TWILIO_SMS_FROM: Optional[str] = Field(default=None, description="Twilio sender phone in E.164, e.g. +972...")
    TWILIO_WHATSAPP_FROM: Optional[str] = Field(default=None, description="Twilio WhatsApp sender, e.g. whatsapp:+972...")
    
    # =========================================================================
    # Logging and Monitoring
    # =========================================================================
    
    # Logging configuration
    LOG_LEVEL: str = Field(default="DEBUG")
    LOG_FORMAT: Literal["json", "pretty"] = Field(default="json")
    
    # Sentry for error tracking
    SENTRY_DSN: Optional[str] = Field(default=None, description="Sentry DSN for error tracking")
    
    # Metrics and health checks
    METRICS_ENABLED: bool = Field(default=True)
    HEALTH_CHECK_PATH: str = Field(default="/health")
    
    # =========================================================================
    # Internationalization
    # =========================================================================
    
    # Supported languages
    SUPPORTED_LANGUAGES: List[str] = Field(default=["he", "ar", "en"])
    DEFAULT_LANGUAGE: str = Field(default="he")
    
    # =========================================================================
    # Background Jobs Configuration
    # =========================================================================
    
    # RQ Worker configuration
    ENABLE_WORKERS: bool = Field(default=False, description="Enable RQ workers (separate service recommended)")
    WORKER_PROCESSES: int = Field(default=2, description="Number of worker processes")
    WORKER_TIMEOUT: int = Field(default=300, description="Worker job timeout in seconds")
    
    # Job retry configuration
    JOB_MAX_RETRIES: int = Field(default=3)
    JOB_RETRY_DELAY: int = Field(default=60, description="Delay between retries in seconds")
    
    # =========================================================================
    # Business Logic Configuration
    # =========================================================================
    
    # Report settings
    REPORT_EXPIRY_DAYS: int = Field(default=30, description="Days before reports expire")
    MAX_REPORTS_PER_USER_PER_DAY: int = Field(default=10)
    
    # Search radius for organizations (in kilometers)
    SEARCH_RADIUS_KM: float = Field(default=20.0)
    MAX_SEARCH_RADIUS_KM: float = Field(default=50.0)
    
    # Alert settings
    ALERT_TIMEOUT_MINUTES: int = Field(default=15, description="Minutes before alert timeout")
    MAX_ALERTS_PER_REPORT: int = Field(default=5)
    
    # Trust system
    ENABLE_TRUST_SYSTEM: bool = Field(default=True)
    MIN_TRUST_SCORE: float = Field(default=0.0)
    MAX_TRUST_SCORE: float = Field(default=10.0)
    
    # =========================================================================
    # Development and Testing
    # =========================================================================
    
    # Testing
    TESTING: bool = Field(default=False)
    TEST_DATABASE_URL: Optional[str] = Field(default=None)
    
    # Development helpers
    AUTO_RELOAD: bool = Field(default=False)
    SHOW_DOCS: bool = Field(default=True, description="Show API documentation")
    
    # =========================================================================
    # Validation and Post-Processing
    # =========================================================================
    
    @field_validator('CORS_ORIGINS', mode='before')
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str) and not v.startswith('['):
            return [i.strip() for i in v.split(',')]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(f"Invalid CORS_ORIGINS: {v}")
    
    @field_validator('UPLOAD_DIR')
    def ensure_upload_dir_exists(cls, v: Path) -> Path:
        """Ensure upload directory exists."""
        v = Path(v)
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @model_validator(mode='after')
    def validate_storage_config(self) -> 'Settings':
        """Validate storage configuration."""
        if self.STORAGE_BACKEND in ["s3", "r2"]:
            required_fields = [
                "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", 
                "S3_SECRET_ACCESS_KEY", "S3_BUCKET_NAME"
            ]
            for field in required_fields:
                if not getattr(self, field):
                    raise ValueError(f"{field} is required when using {self.STORAGE_BACKEND} storage")
        return self
    
    @model_validator(mode='after')
    def validate_email_config(self) -> 'Settings':
        """Validate email configuration."""
        email_fields = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAILS_FROM_EMAIL"]
        if any(getattr(self, field) for field in email_fields):
            # If any email field is set, require all
            for field in email_fields:
                if not getattr(self, field):
                    raise ValueError(f"{field} is required when email is configured")
        return self

    @model_validator(mode='after')
    def _normalize_lock_intervals(self) -> 'Settings':
        """Compute sensible defaults for lock heartbeat interval."""
        hb = self.LOCK_HEARTBEAT_INTERVAL
        if not hb or hb <= 0:
            computed = max(5, int(self.LOCK_LEASE_SECONDS * 0.4))
            object.__setattr__(self, "LOCK_HEARTBEAT_INTERVAL", computed)
        return self
    
    # =========================================================================
    # Environment-specific configurations
    # =========================================================================
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.ENVIRONMENT == "development"
    
    @property
    def is_testing(self) -> bool:
        """Check if running tests."""
        return self.ENVIRONMENT == "testing" or self.TESTING
    
    # =========================================================================
    # Computed Properties
    # =========================================================================
    
    @property
    def DATABASE_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Database engine configuration options."""
        return {
            "pool_size": self.DATABASE_POOL_SIZE,
            "max_overflow": self.DATABASE_MAX_OVERFLOW,
            "pool_timeout": self.DATABASE_POOL_TIMEOUT,
            "echo": self.DATABASE_ECHO and not self.is_production,
            "echo_pool": self.DEBUG and not self.is_production,
            "pool_pre_ping": True,  # Validate connections before use
            "pool_recycle": 3600,   # Recycle connections every hour
        }
    
    # =========================================================================
    # Model Configuration
    # =========================================================================
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "env_nested_delimiter": "__",  # Allow nested config via ENV_VAR__NESTED_VAR
        "validate_assignment": True,   # Validate on assignment
        "extra": "ignore",            # Ignore unknown fields
    }


# =============================================================================
# Settings Instance and Cache
# =============================================================================

@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    This function is cached to avoid re-parsing environment variables
    on every call. In development, you may need to clear the cache
    if you change environment variables.
    """
    return Settings()


# Convenience alias for global access
settings = get_settings()


# =============================================================================
# Logging Configuration
# =============================================================================

def setup_logging() -> None:
    """Configure structured logging for the application."""
    import structlog
    import re

    # Processor to ensure exc_info=True is attached when logging inside an exception block
    def _ensure_exc_info_processor(logger, method_name, event_dict):
        if event_dict.get("exc_info"):
            return event_dict
        if method_name in ("error", "exception", "critical"):
            import sys
            if sys.exc_info()[0] is not None:
                event_dict["exc_info"] = True
        return event_dict

    # Secret redaction filter
    SENSITIVE_KEYS = {"authorization", "token", "api_key", "password", "secret", "dsn"}
    token_pattern = re.compile(r"(bot\d+:[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9._-]+|AIza[0-9A-Za-z_-]{35}|sk-[A-Za-z0-9]{20,})")

    def redact_secrets(_, __, event_dict):
        # Redact obvious tokens in string fields
        for key, value in list(event_dict.items()):
            try:
                if isinstance(value, str):
                    event_dict[key] = token_pattern.sub("***REDACTED***", value)
                elif isinstance(value, dict):
                    for k in list(value.keys()):
                        if k and k.lower() in SENSITIVE_KEYS:
                            value[k] = "***REDACTED***"
            except Exception:
                pass
        # Explicitly redact configured sensitive settings
        for sensitive in ("TELEGRAM_BOT_TOKEN", "SECRET_KEY", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "SENTRY_DSN", "S3_SECRET_ACCESS_KEY"):
            if sensitive in event_dict:
                event_dict[sensitive] = "***REDACTED***"
        return event_dict

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            _ensure_exc_info_processor,
            redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.dev.ConsoleRenderer()
                if settings.LOG_FORMAT == "pretty"
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper())
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format="%(message)s" if settings.LOG_FORMAT == "json" else None,
    )

    # Attach redaction filter to standard logging to catch third-party logs
    class _StdlibRedactFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            try:
                # Redact in main message
                if isinstance(record.msg, str):
                    record.msg = token_pattern.sub("***REDACTED***", record.msg)
                # Redact in args (when message uses formatting)
                if record.args:
                    if isinstance(record.args, dict):
                        for k, v in list(record.args.items()):
                            if isinstance(v, str):
                                record.args[k] = token_pattern.sub("***REDACTED***", v)
                    elif isinstance(record.args, tuple):
                        redacted_args = list(record.args)
                        for i, v in enumerate(redacted_args):
                            if isinstance(v, str):
                                redacted_args[i] = token_pattern.sub("***REDACTED***", v)
                        record.args = tuple(redacted_args)
                # Also scan common attributes for embedded secrets
                for attr in ("message", "pathname", "filename"):
                    val = getattr(record, attr, None)
                    if isinstance(val, str):
                        setattr(record, attr, token_pattern.sub("***REDACTED***", val))
            except Exception:
                pass
            return True

    root_logger = logging.getLogger()
    root_logger.addFilter(_StdlibRedactFilter())

    # Suppress noisy loggers in production
    if settings.is_production:
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        # Quiet noisy Telegram library logs in production
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("telegram.ext").setLevel(logging.WARNING)
        logging.getLogger("telegram.bot").setLevel(logging.WARNING)


# =============================================================================
# Utility Functions
# =============================================================================

def get_database_url(for_testing: bool = False) -> str:
    """Get database URL, optionally for testing."""
    if for_testing and settings.TEST_DATABASE_URL:
        return settings.TEST_DATABASE_URL
    return str(settings.DATABASE_URL)


def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature is enabled via environment variable."""
    env_var = f"ENABLE_{feature_name.upper()}"
    return getattr(settings, env_var, False)


# =============================================================================
# Development Helpers
# =============================================================================

if __name__ == "__main__":
    # Print current configuration for debugging
    import json
    from pydantic import BaseModel
    
    # Create a serializable version of settings
    config_dict = settings.model_dump()
    
    # Remove sensitive information
    sensitive_fields = [
        "SECRET_KEY", "TELEGRAM_BOT_TOKEN", "POSTGRES_PASSWORD",
        "REDIS_PASSWORD", "GOOGLE_PLACES_API_KEY", "SMTP_PASSWORD",
        "S3_SECRET_ACCESS_KEY", "SENTRY_DSN"
    ]
    
    for field in sensitive_fields:
        if field in config_dict:
            config_dict[field] = "***REDACTED***"
    
    print(json.dumps(config_dict, indent=2, default=str))
