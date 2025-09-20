"""
FastAPI Application Entry Point
נקודת הכניסה של אפליקציית FastAPI

This module sets up the FastAPI application with all middleware,
routing, and configuration for the Animal Rescue Bot system.
"""

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import Counter, Histogram, generate_latest
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse

from app.core.config import settings, setup_logging
from app.models.database import engine, create_tables, check_database_health, wait_for_database
from app.core.security import get_current_user
from app.core.exceptions import (
    AnimalRescueException,
    ValidationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

# =============================================================================
# Metrics Collection
# =============================================================================

# Prometheus metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

TELEGRAM_MESSAGES = Counter(
    'telegram_messages_total',
    'Total Telegram messages processed',
    ['message_type', 'status']
)

REPORTS_CREATED = Counter(
    'reports_created_total',
    'Total reports created',
    ['urgency_level', 'animal_type']
)

ALERTS_SENT = Counter(
    'alerts_sent_total',
    'Total alerts sent to organizations',
    ['channel', 'status']
)

DATABASE_QUERIES = Counter(
    'database_queries_total',
    'Total database queries',
    ['operation', 'table']
)

# =============================================================================
# Application Lifespan Management
# =============================================================================

def _check_runtime_dependencies() -> None:
    """
    בדיקת תלויות קריטיות בזמן עליית השרת.
    אם חסרות חבילות חיוניות (למשל tenacity), נזרוק שגיאה עם לוג ברור.
    """
    logger = structlog.get_logger(__name__)
    required_modules = [
        "tenacity",
        "httpx",
        "redis",
        "rq",
        "telegram",
        "aiofiles",  # used by app.services.email
    ]
    missing: Dict[str, str] = {}
    for module_name in required_modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - נרצה את ההודעה המקורית
            missing[module_name] = str(exc)
    if missing:
        logger.error(
            "❌ Missing required Python packages",
            missing=list(missing.keys()),
            details=missing,
            fix=(
                "Add the missing packages to requirements.txt and rebuild/redeploy. "
                "On Render: trigger a deploy to install updated dependencies."
            ),
        )
        raise RuntimeError(
            f"Missing required Python packages: {', '.join(missing.keys())}"
        )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events for proper resource management.
    """
    # Setup logging early before any logger usage
    setup_logging()
    # Bind global context to all logs
    structlog.contextvars.bind_contextvars(
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.APP_VERSION,
    )
    logger = structlog.get_logger(__name__)
    
    # Startup
    logger.info("🚀 Starting Animal Rescue Bot application", version=settings.APP_VERSION, environment=settings.ENVIRONMENT)
    logger.info("📝 Logging configured", log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    
    # בדיקת תלויות לפני כל ייבוא/אתחול שעלול לדרוש אותן
    _check_runtime_dependencies()

    # רישום ראוטרים בצורה עצלה לאחר בדיקת התלויות
    try:
        from app.api.v1.api import api_router
        from app.bot.webhook import telegram_router

        # Always include core routers
        app.include_router(
            api_router,
            prefix=settings.API_V1_PREFIX,
            tags=["API v1"],
        )
        app.include_router(
            telegram_router,
            prefix="/telegram",
            tags=["Telegram Bot"],
        )

        # Try to include admin router if available (optional)
        try:
            from admin.routes import admin_router  # Top-level "admin" package
            app.include_router(
                admin_router,
                prefix="/admin",
                tags=["Admin Interface"],
            )
            logger.info("🧭 Routers registered (with admin)")
        except ModuleNotFoundError as exc:
            logger.warning("⚠️ Admin module missing - skipping admin routes", error=str(exc))
            logger.info("🧭 Routers registered (without admin)")
    except Exception as e:
        logger.error("❌ Failed to register core routers", error=str(e), exc_info=True)
        raise

    # Initialize database
    try:
        # Wait for DB to be ready (useful in container orchestration)
        await wait_for_database()
        await create_tables()
        logger.info("🗄️ Database tables initialized")
        
        # Test database connectivity
        db_health = await check_database_health()
        if db_health["status"] == "healthy":
            logger.info("✅ Database connection verified", **db_health)
        else:
            logger.error("❌ Database health check failed", **db_health)
            
    except Exception as e:
        logger.error("💥 Database initialization failed", error=str(e))
        raise
    
    # Initialize Redis connection
    try:
        from app.core.cache import redis_client
        await redis_client.ping()
        logger.info("✅ Redis connection verified")
    except Exception as e:
        logger.error("❌ Redis connection failed", error=str(e))
        # Redis is critical for background jobs
        raise
    
    # Start background workers if enabled and not in testing mode
    if not settings.is_testing and settings.ENABLE_WORKERS:
        try:
            from app.workers.manager import start_workers
            await start_workers()
            logger.info("👷 Background workers started")
        except Exception as e:
            logger.error("❌ Failed to start workers", error=str(e))
    
    # Initialize external services
    try:
        from app.services.google import GoogleService
        google_service = GoogleService()
        if await google_service.test_connection():
            logger.info("🗺️ Google APIs connection verified")
        else:
            logger.warning("⚠️ Google APIs not available")
    except Exception as e:
        logger.warning("⚠️ Google APIs initialization failed", error=str(e))
    
    # Initialize Telegram bot
    if not settings.is_testing:
        try:
            from app.bot.handlers import bot, initialize_bot, start_polling_if_needed
            await initialize_bot()
            logger.info("🤖 Telegram bot initialized")
            try:
                started = await start_polling_if_needed()
                if started:
                    logger.info("📡 Telegram polling started (webhook not configured)")
            except Exception as e:
                logger.error("❌ Telegram polling start failed", error=str(e))
        except Exception as e:
            logger.error("❌ Telegram bot initialization failed", error=str(e))
    
    logger.info(
        "🎉 Application startup completed successfully",
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG
    )
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Animal Rescue Bot application")
    
    # Cleanup resources
    try:
        await engine.dispose()
        logger.info("🗄️ Database engine disposed")
        
        from app.core.cache import redis_client
        await redis_client.close()
        logger.info("📊 Redis connection closed")
        # Stop Telegram bot/polling gracefully
        try:
            from app.bot.handlers import shutdown_bot
            await shutdown_bot()
            logger.info("🤖 Telegram bot shutdown completed")
        except Exception as e:
            logger.warning("⚠️ Telegram bot shutdown error", error=str(e))
        
    except Exception as e:
        logger.error("⚠️ Error during shutdown", error=str(e))
    
    logger.info("✅ Application shutdown completed")


# =============================================================================
# FastAPI Application Setup
# =============================================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.SHOW_DOCS else None,
    docs_url="/docs" if settings.SHOW_DOCS else None,
    redoc_url="/redoc" if settings.SHOW_DOCS else None,
    lifespan=lifespan,
    # Security headers
    swagger_ui_oauth2_redirect_url=None,
    swagger_ui_init_oauth=None,
)

# =============================================================================
# Middleware Configuration
# =============================================================================

# Security middleware
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure with actual hosts in production
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Session middleware for admin interface
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    https_only=settings.is_production,
    same_site="strict" if settings.is_production else "lax",
)

# Compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# =============================================================================
# Request/Response Middleware
# =============================================================================

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Log all requests and add request ID for tracing.
    """
    import uuid
    import time
    
    # Generate request ID
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    
    # Get logger with request context
    logger = structlog.get_logger(__name__).bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host,
        user_agent=request.headers.get("user-agent", ""),
    )
    
    # Record request start time
    start_time = time.time()
    
    # Log incoming request
    logger.info("📥 Incoming request")
    
    try:
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Update metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code
        ).inc()
        
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        
        # Add response headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        
        # Log response
        logger.info(
            "📤 Request completed",
            status_code=response.status_code,
            duration=f"{duration:.3f}s"
        )
        
        return response
        
    except Exception as exc:
        duration = time.time() - start_time
        
        # Log error
        logger.error(
            "💥 Request failed",
            error=str(exc),
            duration=f"{duration:.3f}s",
            exc_info=True
        )
        
        # Update error metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=500
        ).inc()
        
        raise


@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """
    Basic rate limiting middleware.
    """
    from app.core.rate_limit import check_rate_limit, RateLimitExceeded
    
    try:
        # Skip rate limiting for health checks, docs, static, and Telegram webhook
        path = request.url.path
        excluded = {
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            f"{settings.API_V1_PREFIX}/openapi.json",
        }
        if (
            path in excluded
            or path.startswith("/static")
            or path.startswith("/uploads")
            or path.startswith("/telegram/webhook")
        ):
            return await call_next(request)
        
        # Get client identifier
        client_id = request.client.host
        if "authorization" in request.headers:
            # For authenticated requests, use user ID
            try:
                user = await get_current_user(request.headers["authorization"])
                client_id = f"user:{user.id}"
            except:
                pass  # Fall back to IP-based limiting
        
        # Check rate limit
        await check_rate_limit(client_id, path)
        
        return await call_next(request)
        
    except RateLimitExceeded as e:
        # Return structured 429 response without triggering 500 error handler logs
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": True,
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit exceeded. Try again in {e.retry_after} seconds.",
                "retry_after": e.retry_after,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": getattr(request.state, "request_id", None),
            },
            headers={"Retry-After": str(e.retry_after)}
        )


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(AnimalRescueException)
async def animal_rescue_exception_handler(request: Request, exc: AnimalRescueException):
    """Handle custom application exceptions."""
    logger = structlog.get_logger(__name__).bind(
        request_id=getattr(request.state, "request_id", "unknown"),
        error_code=exc.error_code,
        error_type=type(exc).__name__,
    )
    
    logger.error("🚨 Application error", error=str(exc))
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": getattr(request.state, "request_id", None),
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    logger = structlog.get_logger(__name__).bind(
        request_id=getattr(request.state, "request_id", "unknown"),
    )
    
    logger.warning("⚠️ Validation error", errors=exc.errors())
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Input validation failed",
            "details": exc.errors(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": getattr(request.state, "request_id", None),
        }
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Handle 404 errors with custom response."""
    return JSONResponse(
        status_code=404,
        content={
            "error": True,
            "error_code": "NOT_FOUND",
            "message": "The requested resource was not found",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": getattr(request.state, "request_id", None),
        }
    )


@app.exception_handler(500)
async def internal_server_error_handler(request: Request, exc: Exception):
    """Handle internal server errors."""
    logger = structlog.get_logger(__name__).bind(
        request_id=getattr(request.state, "request_id", "unknown"),
    )
    
    logger.error("💥 Internal server error", error=str(exc), exc_info=True)
    
    # In production, don't expose internal error details
    error_message = (
        "An internal server error occurred" 
        if settings.is_production 
        else str(exc)
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "error_code": "INTERNAL_ERROR",
            "message": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": getattr(request.state, "request_id", None),
        }
    )


# =============================================================================
# Health Check and Monitoring Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """
    Application health check endpoint.
    
    Returns comprehensive health information about all services.
    """
    health_data = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "services": {}
    }
    
    # Check database
    try:
        db_health = await check_database_health()
        health_data["services"]["database"] = db_health
        # Bubble up concise PostGIS status when available
        if isinstance(db_health, dict) and "postgis" in db_health:
            health_data["services"]["postgis"] = db_health["postgis"]
    except Exception as e:
        health_data["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # Check Redis
    try:
        from app.core.cache import redis_client
        await redis_client.ping()
        health_data["services"]["redis"] = {"status": "healthy"}
    except Exception as e:
        health_data["services"]["redis"] = {
            "status": "unhealthy", 
            "error": str(e)
        }
        health_data["status"] = "degraded"
    
    # Check external APIs
    try:
        from app.services.google import GoogleService
        google_service = GoogleService()
        if await google_service.test_connection():
            health_data["services"]["google_apis"] = {"status": "healthy"}
        else:
            health_data["services"]["google_apis"] = {"status": "unavailable"}
    except Exception as e:
        health_data["services"]["google_apis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    # Check Telegram bot
    if not settings.is_testing:
        try:
            from app.bot.handlers import bot
            bot_info = await bot.get_me()
            health_data["services"]["telegram_bot"] = {
                "status": "healthy",
                "bot_username": bot_info.username
            }
        except Exception as e:
            health_data["services"]["telegram_bot"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_data["status"] = "degraded"
    
    # Determine overall health
    unhealthy_services = [
        name for name, service in health_data["services"].items()
        if service.get("status") == "unhealthy"
    ]
    
    if unhealthy_services:
        health_data["status"] = "unhealthy"
        health_data["unhealthy_services"] = unhealthy_services
    
    # Return appropriate status code
    status_code = (
        200 if health_data["status"] == "healthy"
        else 503 if health_data["status"] == "unhealthy"
        else 200  # degraded but still operational
    )
    
    return JSONResponse(content=health_data, status_code=status_code)


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(generate_latest())


@app.get("/version")
async def version_info():
    """Application version information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": settings.APP_DESCRIPTION,
        "environment": settings.ENVIRONMENT,
        "python_version": "3.12+",
        "build_time": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Static Files and Assets
# =============================================================================

# Serve uploaded files (only in development)
if settings.is_development:
    uploads_dir = settings.UPLOAD_DIR
    uploads_dir.mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# Serve static assets for admin interface
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# =============================================================================
# API Routes
# =============================================================================
"""
רישום הראוטרים מועבר ל-lifespan כדי לאפשר בדיקת תלויות לפני ייבוא
מודולים שעלולים לדרוש חבילות חיצוניות. השארנו את הכותרות כאן לשימור מבנה הקובץ.
"""


# =============================================================================
# Root Endpoints
# =============================================================================

@app.get("/")
async def root():
    """API root endpoint with basic information."""
    return {
        "message": "🐾 Animal Rescue Bot API",
        "version": settings.APP_VERSION,
        "docs_url": "/docs" if settings.SHOW_DOCS else None,
        "health_url": "/health",
        "api_prefix": settings.API_V1_PREFIX,
        "telegram_bot": True,
        "environment": settings.ENVIRONMENT,
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint to avoid 404s."""
    return Response(status_code=204)


# =============================================================================
# Development and Testing Utilities
# =============================================================================

if settings.is_development:
    
    @app.post("/dev/trigger-test-alert")
    async def trigger_test_alert():
        """Trigger a test alert for development."""
        from app.workers.jobs import send_test_alert, enqueue_or_run
        
        job = enqueue_or_run(send_test_alert, "Test alert from development endpoint")
        return {"message": "Test alert queued", "job_id": getattr(job, 'id', None)}
    
    @app.get("/dev/db-stats")
    async def database_stats():
        """Get database statistics for development."""
        from sqlalchemy import text
        from app.models.database import async_session_maker
        
        async with async_session_maker() as session:
            stats = {}
            
            tables = ["users", "organizations", "reports", "alerts", "events"]
            for table in tables:
                result = await session.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                )
                stats[table] = result.scalar()
            
            return {"database_stats": stats}


# =============================================================================
# Application Factory
# =============================================================================

def create_app() -> FastAPI:
    """
    Application factory function.
    
    Returns:
        Configured FastAPI application instance
    """
    return app


# =============================================================================
# CLI and Development Server
# =============================================================================

if __name__ == "__main__":
    """
    Run the application directly for development.
    
    For production, use: uvicorn app.main:app --host 0.0.0.0 --port 8000
    Or with gunicorn: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
    """
    
    # Configure logging for development
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run with uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.AUTO_RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=not settings.is_production,
        server_header=False,
        date_header=False,
    )
