# 📚 ספריית Code Snippets – בוטים וטלגרם

> סניפטים נוספים לספריית Code Keeper המקורית  
> תבניות קוד מוכנות להעתקה מפרויקט Animals Rescue Bot

---

## 9.x – Background Jobs ו-RQ

### ✅ 9.1 – RQ Job Definition עם Retry ו-Timeout

**למה זה שימושי:** יצירת background job עם RQ כולל retry אוטומטי וטיימאאוט

```python
from rq import Retry
from rq.decorators import job
from app.core.cache import redis_queue_sync

@job("default", timeout="10m", retry=Retry(max=3, interval=60), connection=redis_queue_sync)
def process_new_report(report_id: str):
    """
    Process a newly submitted report.
    
    Args:
        report_id: UUID string of the report to process
    """
    logger.info("Processing report", report_id=report_id)
    
    try:
        # Run async code from sync job
        return asyncio.run(_process_new_report_async(report_id))
    except Exception as e:
        logger.error("Failed to process report", report_id=report_id, error=str(e))
        raise  # Re-raise for RQ retry mechanism
```

---

### ✅ 9.2 – Enqueue or Run Inline Pattern

**למה זה שימושי:** תמיכה ב-workers וגם במצב ללא workers (development)

```python
def enqueue_or_run(func, *args, **kwargs):
    """
    Enqueue an RQ job when workers enabled, otherwise run inline.
    
    Example:
        enqueue_or_run(process_new_report, report_id=str(report.id))
    """
    if settings.ENABLE_WORKERS:
        # Production: Queue to RQ worker
        return func.delay(*args, **kwargs)
    else:
        # Development: Run inline
        if asyncio.iscoroutinefunction(func):
            return asyncio.create_task(func(*args, **kwargs))
        else:
            return func(*args, **kwargs)
```

---

### ✅ 9.3 – RQ Scheduler – Recurring Jobs

**למה זה שימושי:** תזמון משימות חוזרות (cleanup, stats, sync)

```python
from rq_scheduler import Scheduler
from app.core.cache import redis_queue_sync

def schedule_recurring_jobs():
    """Schedule recurring background jobs."""
    scheduler = Scheduler(connection=redis_queue_sync)
    
    # Daily cleanup at 2 AM
    scheduler.cron(
        cron_string="0 2 * * *",  # Every day at 2 AM
        func=cleanup_old_data,
        timeout="30m",
        use_local_timezone=False
    )
    
    # Update stats every 6 hours
    scheduler.cron(
        cron_string="0 */6 * * *",
        func=update_organization_stats,
        timeout="10m",
        use_local_timezone=False
    )
    
    logger.info("Recurring jobs scheduled")
```

---

## 10.x – Telegram Bot Setup

### ✅ 10.1 – Webhook Handler עם Secret Verification

**למה זה שימושי:** קבלת updates מטלגרם עם אימות secret token

```python
from fastapi import APIRouter, HTTPException, Request, Response, status
from telegram import Update

telegram_router = APIRouter()

@telegram_router.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Handle incoming Telegram webhook updates."""
    
    # Verify webhook secret
    if settings.TELEGRAM_WEBHOOK_SECRET:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_header != settings.TELEGRAM_WEBHOOK_SECRET:
            logger.warning("Invalid webhook secret", remote_addr=request.client.host)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret"
            )
    
    # Parse request body
    body = await request.body()
    if not body:
        return Response(status_code=200)
    
    update_data = json.loads(body.decode('utf-8'))
    update = Update.de_json(update_data, bot_application.bot)
    
    if not update:
        return Response(status_code=200)
    
    # Process update
    await bot_application.process_update(update)
    
    # Always return 200 OK to prevent Telegram retries
    return Response(status_code=200)
```

---

### ✅ 10.2 – Telegram Message Formatting עם HTML

**למה זה שימושי:** עיצוב הודעות טלגרם בטוח עם escape של HTML

```python
class TelegramFormatter:
    """Formats messages for Telegram with proper escaping."""
    
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
    def link(text: str, url: str) -> str:
        """Create a link."""
        return f'<a href="{url}">{TelegramFormatter.escape_html(text)}</a>'
```

---

### ✅ 10.3 – Inline Keyboard Builder

**למה זה שימושי:** יצירת תפריטים מותאמים אישית בטלגרם

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def create_inline_keyboard(buttons: List[List[dict]]) -> InlineKeyboardMarkup:
    """
    Create inline keyboard from button data.
    
    Args:
        buttons: List of button rows, each button is a dict with:
                 - text: Button text
                 - callback_data: Data for callback (optional)
                 - url: URL to open (optional)
    
    Example:
        buttons = [
            [{"text": "✅ אישור", "callback_data": "confirm_123"}],
            [{"text": "❌ ביטול", "callback_data": "cancel_123"}]
        ]
    """
    keyboard = []
    
    for button_row in buttons:
        row = []
        for button in button_row:
            if button.get("callback_data"):
                btn = InlineKeyboardButton(
                    text=button["text"],
                    callback_data=button["callback_data"]
                )
            elif button.get("url"):
                btn = InlineKeyboardButton(
                    text=button["text"],
                    url=button["url"]
                )
            else:
                continue
            row.append(btn)
        
        if row:
            keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)
```

---

## 11.x – Database ו-SQLAlchemy Async

### ✅ 11.1 – Async Database Session Context Manager

**למה זה שימושי:** ניהול session אוטומטי עם סגירה בטוחה

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    echo=settings.DATABASE_ECHO,
    pool_pre_ping=True,  # Validate connections before use
    pool_recycle=3600,   # Recycle connections every hour
)

# Create session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Usage in code
async def some_database_operation():
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        # Modify user
        user.last_login_at = datetime.now(timezone.utc)
        
        await session.commit()
        await session.refresh(user)
        
        return user
```

---

### ✅ 11.2 – Eager Loading עם selectinload

**למה זה שימושי:** טעינת relationships בשאילתה אחת למניעת N+1

```python
from sqlalchemy.orm import selectinload

async def get_report_with_relations(report_id: uuid.UUID, session: AsyncSession):
    """Get report with all related data loaded."""
    
    query = select(Report).where(Report.id == report_id).options(
        selectinload(Report.reporter),              # Load reporter user
        selectinload(Report.files),                 # Load files
        selectinload(Report.alerts).selectinload(Alert.organization),  # Nested load
        selectinload(Report.assigned_organization)
    )
    
    result = await session.execute(query)
    report = result.scalar_one_or_none()
    
    return report
```

---

### ✅ 11.3 – Complex Filter עם and_ / or_

**למה זה שימושי:** בניית שאילתות מורכבות עם תנאים מרובים

```python
from sqlalchemy import select, and_, or_, desc

async def search_reports(
    session: AsyncSession,
    animal_type: Optional[AnimalType] = None,
    urgency_level: Optional[UrgencyLevel] = None,
    city: Optional[str] = None,
    date_from: Optional[datetime] = None,
    status_list: Optional[List[ReportStatus]] = None
):
    """Search reports with multiple filters."""
    
    # Build conditions list
    conditions = []
    
    if animal_type:
        conditions.append(Report.animal_type == animal_type)
    
    if urgency_level:
        conditions.append(Report.urgency_level == urgency_level)
    
    if city:
        conditions.append(Report.city.ilike(f"%{city}%"))
    
    if date_from:
        conditions.append(Report.created_at >= date_from)
    
    if status_list:
        conditions.append(Report.status.in_(status_list))
    
    # Combine all conditions with AND
    query = select(Report)
    if conditions:
        query = query.where(and_(*conditions))
    
    # Order by created_at descending
    query = query.order_by(desc(Report.created_at))
    
    result = await session.execute(query)
    reports = result.scalars().all()
    
    return reports
```

---

### ✅ 11.4 – Location-Based Query (Bounding Box)

**למה זה שימושי:** חיפוש ישויות לפי קרבה גיאוגרפית

```python
async def find_organizations_near_location(
    latitude: float,
    longitude: float,
    radius_km: float,
    session: AsyncSession
) -> List[Organization]:
    """Find organizations within radius of location."""
    
    # Calculate bounding box (approximate)
    lat_delta = radius_km / 111  # ~111 km per degree latitude
    lon_delta = radius_km / (111 * 0.7)  # Rough longitude correction
    
    query = select(Organization).where(
        and_(
            Organization.is_active == True,
            Organization.latitude.isnot(None),
            Organization.longitude.isnot(None),
            Organization.latitude.between(
                latitude - lat_delta,
                latitude + lat_delta
            ),
            Organization.longitude.between(
                longitude - lon_delta,
                longitude + lon_delta
            )
        )
    ).limit(20)
    
    result = await session.execute(query)
    organizations = result.scalars().all()
    
    # Calculate exact distances and filter
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate distance in km using Haversine formula."""
        import math
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        return 6371 * 2 * math.asin(math.sqrt(a))
    
    filtered = []
    for org in organizations:
        distance = haversine_distance(latitude, longitude, org.latitude, org.longitude)
        if distance <= radius_km:
            org._distance = distance  # Store for sorting
            filtered.append(org)
    
    # Sort by distance
    filtered.sort(key=lambda o: o._distance)
    
    return filtered
```

---

## 12.x – Error Handling ו-Exceptions

### ✅ 12.1 – Custom Exception Hierarchy

**למה זה שימושי:** exceptions מובנות עם metadata לטיפול בשגיאות

```python
class AnimalRescueException(Exception):
    """Base exception for all application errors."""
    
    def __init__(
        self,
        message: str = "An error occurred",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(AnimalRescueException):
    """Raised when data validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details={"field": field} if field else {}
        )


class NotFoundError(AnimalRescueException):
    """Raised when a resource is not found."""
    
    def __init__(self, resource: str, identifier: Optional[str] = None):
        message = f"{resource} not found"
        if identifier:
            message += f" (ID: {identifier})"
        
        super().__init__(
            message=message,
            error_code="RESOURCE_NOT_FOUND",
            details={"resource": resource, "identifier": identifier}
        )
```

---

### ✅ 12.2 – FastAPI Exception Handler

**למה זה שימושי:** טיפול מרוכז בשגיאות עם לוגים מובנים

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(AnimalRescueException)
async def animal_rescue_exception_handler(request: Request, exc: AnimalRescueException):
    """Handle custom application exceptions."""
    
    logger = structlog.get_logger(__name__).bind(
        request_id=getattr(request.state, "request_id", "unknown"),
        error_code=exc.error_code,
        error_type=type(exc).__name__,
    )
    
    logger.error("Application error", error=str(exc), details=exc.details)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "error_code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": getattr(request.state, "request_id", None),
        }
    )
```

---

### ✅ 12.3 – Retry Logic עם Exponential Backoff

**למה זה שימושי:** נסיונות חוזרים חכמים לשירותים חיצוניים

```python
import asyncio
from typing import TypeVar, Callable

T = TypeVar('T')

async def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    *args,
    **kwargs
) -> T:
    """
    Retry function with exponential backoff.
    
    Example:
        result = await retry_with_backoff(
            external_api_call,
            max_retries=5,
            base_delay=1.0,
            api_key=key
        )
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        
        except Exception as e:
            last_exception = e
            
            if attempt == max_retries - 1:
                # Last attempt failed
                break
            
            # Calculate delay with exponential backoff
            delay = min(
                base_delay * (exponential_base ** attempt),
                max_delay
            )
            
            logger.warning(
                "Retry attempt failed",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e)
            )
            
            await asyncio.sleep(delay)
    
    # All retries failed
    logger.error(
        "All retry attempts failed",
        max_retries=max_retries,
        error=str(last_exception)
    )
    raise last_exception
```

---

## 13.x – Logging ו-Monitoring

### ✅ 13.1 – Structured Logging עם structlog

**למה זה שימושי:** לוגים מובנים עם context וסינון סודות

```python
import structlog
import logging

def setup_logging():
    """Configure structured logging with secret redaction."""
    
    # Secret redaction processor
    SENSITIVE_KEYS = {"authorization", "token", "api_key", "password", "secret"}
    
    def redact_secrets(_, __, event_dict):
        """Redact sensitive information from logs."""
        for key, value in list(event_dict.items()):
            if key.lower() in SENSITIVE_KEYS and isinstance(value, str):
                event_dict[key] = "***REDACTED***"
        return event_dict
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            redact_secrets,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

# Usage
logger = structlog.get_logger(__name__)

logger.info(
    "User logged in",
    user_id=user_id,
    username=username,
    ip_address=request.client.host
)
```

---

### ✅ 13.2 – Request Logging Middleware

**למה זה שימושי:** לוג אוטומטי לכל request עם timing ו-request ID

```python
import uuid
import time
from fastapi import Request

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all requests with timing and request ID."""
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    
    # Bind context to logger
    logger = structlog.get_logger(__name__).bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host,
    )
    
    start_time = time.time()
    logger.info("Incoming request")
    
    try:
        # Process request
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"
        
        logger.info(
            "Request completed",
            status_code=response.status_code,
            duration=f"{duration:.3f}s"
        )
        
        return response
    
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            "Request failed",
            error=str(exc),
            duration=f"{duration:.3f}s",
            exc_info=True
        )
        raise
```

---

### ✅ 13.3 – Prometheus Metrics

**למה זה שימושי:** מדדי ביצועים לניטור production

```python
from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import PlainTextResponse

# Define metrics
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

REPORTS_CREATED = Counter(
    'reports_created_total',
    'Total reports created',
    ['urgency_level', 'animal_type']
)

# Update metrics in code
REQUEST_COUNT.labels(
    method=request.method,
    endpoint=request.url.path,
    status_code=response.status_code
).inc()

REQUEST_DURATION.labels(
    method=request.method,
    endpoint=request.url.path
).observe(duration)

# Expose metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(generate_latest())
```

---

## 14.x – File Storage ו-Uploads

### ✅ 14.1 – File Validation with Security Checks

**למה זה שימושי:** בדיקות אבטחה לקבצים שעולים למערכת

```python
from PIL import Image
from io import BytesIO
import mimetypes

def validate_file(file_data: bytes, filename: str, content_type: str) -> None:
    """
    Validate uploaded file for security and constraints.
    
    Raises:
        ValidationError: If file is invalid
    """
    # Check file size
    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(file_data) > max_size:
        raise ValidationError(f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
    
    # Check file type
    if content_type not in settings.ALLOWED_FILE_TYPES:
        raise ValidationError(f"File type {content_type} is not allowed")
    
    # Verify MIME type matches content
    detected_type, _ = mimetypes.guess_type(filename)
    if detected_type and detected_type != content_type:
        logger.warning(
            "MIME type mismatch",
            declared=content_type,
            detected=detected_type
        )
    
    # Security checks for images
    if content_type.startswith('image/'):
        try:
            # Verify it's a valid image
            image = Image.open(BytesIO(file_data))
            image.verify()
            
            # Check dimensions
            if hasattr(image, 'size'):
                width, height = image.size
                if width > 10000 or height > 10000:
                    raise ValidationError("Image dimensions too large")
        
        except Exception as e:
            raise ValidationError(f"Invalid image file: {str(e)}")
    
    # Check for malicious content
    if b'<script' in file_data.lower() or b'javascript:' in file_data.lower():
        raise ValidationError("File contains potentially malicious content")
```

---

### ✅ 14.2 – S3 File Upload

**למה זה שימושי:** העלאת קבצים ל-S3/Cloudflare R2

```python
import boto3
import hashlib
from pathlib import Path

class S3FileStorage:
    """S3-compatible storage backend."""
    
    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.client = boto3.client(
            's3',
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
        )
    
    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        folder: str = ""
    ) -> Dict[str, Any]:
        """Upload file to S3."""
        
        # Generate unique filename
        file_ext = Path(filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{file_ext}"
        
        # Create S3 key
        s3_key = f"{folder.strip('/')}/{unique_name}" if folder else unique_name
        
        # Generate file hash
        file_hash = hashlib.sha256(file_data).hexdigest()
        
        # Upload to S3
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=file_data,
            ContentType=content_type,
            Metadata={
                'original_filename': filename,
                'upload_timestamp': datetime.now(timezone.utc).isoformat(),
                'file_hash': file_hash,
            }
        )
        
        # Generate public URL
        public_url = f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.bucket_name}/{s3_key}"
        
        return {
            "path": s3_key,
            "url": public_url,
            "hash": file_hash,
            "size": len(file_data),
            "backend": "s3",
        }
```

---

### ✅ 14.3 – Image Thumbnail Generation

**למה זה שימושי:** יצירת thumbnails אוטומטית לתמונות

```python
from PIL import Image
from io import BytesIO

def generate_thumbnail(file_data: bytes, max_size: tuple = (300, 300)) -> Optional[bytes]:
    """
    Generate thumbnail for image.
    
    Args:
        file_data: Original image data
        max_size: Maximum dimensions (width, height)
    
    Returns:
        Thumbnail image bytes as JPEG
    """
    try:
        image = Image.open(BytesIO(file_data))
        
        # Create thumbnail (maintains aspect ratio)
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to RGB if needed (for JPEG)
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        # Save to bytes
        thumbnail_io = BytesIO()
        image.save(thumbnail_io, format='JPEG', quality=85, optimize=True)
        thumbnail_io.seek(0)
        
        return thumbnail_io.getvalue()
    
    except Exception as e:
        logger.warning("Failed to generate thumbnail", error=str(e))
        return None
```

---

## 15.x – Authentication ו-JWT

### ✅ 15.1 – JWT Token Creation

**למה זה שימושי:** יצירת JWT tokens מאובטחים

```python
import jwt
from datetime import datetime, timezone, timedelta

def create_access_token(
    subject: Union[str, int],
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create JWT access token.
    
    Example:
        token = create_access_token(
            subject=str(user.id),
            expires_delta=timedelta(days=7),
            additional_claims={"role": user.role.value}
        )
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    
    if additional_claims:
        to_encode.update(additional_claims)
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm="HS256"
    )
    
    return encoded_jwt
```

---

### ✅ 15.2 – JWT Token Validation Dependency

**למה זה שימושי:** אימות אוטומטי של משתמש מ-JWT

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(
    session: AsyncSession = Depends(get_db_session),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[User]:
    """
    Get current authenticated user from JWT token.
    
    Usage:
        @app.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user_id": str(user.id)}
    """
    if not credentials:
        return None
    
    try:
        # Decode token
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        # Get user from database
        result = await session.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            return None
        
        # Update last activity
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        
        return user
    
    except Exception as e:
        logger.debug("Authentication failed", error=str(e))
        return None
```

---

### ✅ 15.3 – Role-Based Access Control

**למה זה שימושי:** הגבלת גישה לפי תפקידים

```python
def require_roles(allowed_roles: List[UserRole]):
    """
    Create dependency that requires specific roles.
    
    Usage:
        @app.post("/admin/action")
        async def admin_action(
            user: User = Depends(require_roles([UserRole.SYSTEM_ADMIN]))
        ):
            return {"status": "ok"}
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        
        if current_user.role not in allowed_roles:
            logger.warning(
                "Access denied",
                user_id=str(current_user.id),
                user_role=current_user.role.value,
                required_roles=[r.value for r in allowed_roles]
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        
        return current_user
    
    return role_checker
```

---

## 16.x – Redis ו-Caching

### ✅ 16.1 – Redis Lua Script for Atomic Operations

**למה זה שימושי:** פעולות אטומיות מורכבות ב-Redis

```python
async def check_token_bucket_rate_limit(
    key: str,
    capacity: int,
    refill_rate: int,
    window: int = 60
) -> Tuple[bool, int]:
    """
    Token bucket rate limiting with Lua script.
    
    Returns:
        (allowed, retry_after_seconds)
    """
    bucket_key = f"rate_limit:token_bucket:{key}"
    
    # Atomic Lua script for token bucket
    lua_script = """
    local bucket_key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local window = tonumber(ARGV[3])
    local now = tonumber(ARGV[4])
    
    local bucket = redis.call('HMGET', bucket_key, 'tokens', 'last_refill')
    local tokens = tonumber(bucket[1]) or capacity
    local last_refill = tonumber(bucket[2]) or now
    
    -- Calculate tokens to add
    local time_elapsed = now - last_refill
    local tokens_to_add = math.floor(time_elapsed / window * refill_rate)
    tokens = math.min(capacity, tokens + tokens_to_add)
    
    if tokens >= 1 then
        -- Allow request
        tokens = tokens - 1
        redis.call('HMSET', bucket_key, 'tokens', tokens, 'last_refill', now)
        redis.call('EXPIRE', bucket_key, window * 2)
        return {1, 0}
    else
        -- Deny request
        redis.call('HMSET', bucket_key, 'tokens', tokens, 'last_refill', now)
        local retry_after = math.ceil((1 - tokens) / refill_rate * window)
        return {0, retry_after}
    end
    """
    
    current_time = int(time.time())
    
    result = await redis_client.eval(
        lua_script, 1, bucket_key,
        capacity, refill_rate, window, current_time
    )
    
    allowed = bool(result[0])
    retry_after = int(result[1])
    
    return allowed, retry_after
```

---

### ✅ 16.2 – Distributed Lock עם Redis

**למה זה שימושי:** נעילה מבוזרת למניעת race conditions

```python
from contextlib import asynccontextmanager

class DistributedLock:
    """Redis-based distributed lock."""
    
    def __init__(self, key: str, timeout: int = 30):
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.identifier = f"{id(self)}:{time.time()}"
        self._acquired = False
    
    async def acquire(self) -> bool:
        """Acquire the lock."""
        result = await redis_client.set(
            self.key,
            self.identifier,
            nx=True,  # Only set if doesn't exist
            ex=self.timeout  # Expiration
        )
        self._acquired = bool(result)
        return self._acquired
    
    async def release(self) -> bool:
        """Release the lock (only if we own it)."""
        lua_script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('DEL', KEYS[1])
        else
            return 0
        end
        """
        result = await redis_client.eval(lua_script, 1, self.key, self.identifier)
        return bool(result)
    
    async def __aenter__(self):
        if await self.acquire():
            return self
        raise Exception(f"Could not acquire lock: {self.key}")
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

# Usage
async with DistributedLock("process_report", timeout=60):
    # Critical section - only one process can execute this at a time
    await process_report_logic()
```

---

## 17.x – Health Checks ו-Monitoring

### ✅ 17.1 – Comprehensive Health Check

**למה זה שימושי:** בדיקת בריאות כל השירותים

```python
@app.get("/health")
async def health_check():
    """Application health check with all services."""
    
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
    except Exception as e:
        health_data["services"]["database"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"
    
    # Check Redis
    try:
        await redis_client.ping()
        health_data["services"]["redis"] = {"status": "healthy"}
    except Exception as e:
        health_data["services"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"
    
    # Check external APIs
    try:
        google_service = GoogleService()
        if await google_service.test_connection():
            health_data["services"]["google_apis"] = {"status": "healthy"}
        else:
            health_data["services"]["google_apis"] = {"status": "unavailable"}
    except Exception as e:
        health_data["services"]["google_apis"] = {"status": "unhealthy", "error": str(e)}
    
    # Determine overall health
    unhealthy = [name for name, svc in health_data["services"].items() 
                 if svc.get("status") == "unhealthy"]
    
    if unhealthy:
        health_data["status"] = "unhealthy"
        health_data["unhealthy_services"] = unhealthy
    
    status_code = 200 if health_data["status"] in {"healthy", "degraded"} else 503
    
    return JSONResponse(content=health_data, status_code=status_code)
```

---

### ✅ 17.2 – Database Health Check עם PostGIS

**למה זה שימושי:** בדיקת תקינות database כולל extensions

```python
async def check_database_health() -> Dict[str, Any]:
    """Check database connection and extensions."""
    
    async with async_session_maker() as session:
        try:
            # Test basic connection
            result = await session.execute(text("SELECT 1"))
            result.scalar()
            
            # Check PostGIS extension
            postgis_result = await session.execute(
                text("SELECT PostGIS_version()")
            )
            postgis_version = postgis_result.scalar()
            
            return {
                "status": "healthy",
                "engine": "PostgreSQL",
                "postgis": {
                    "installed": True,
                    "version": postgis_version
                }
            }
        
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
```

---

## 18.x – Email ו-Templates

### ✅ 18.1 – Email Template Rendering עם Jinja2

**למה זה שימושי:** שליחת מיילים מעוצבים עם תבניות

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape

class EmailTemplateEngine:
    """Render email templates with Jinja2."""
    
    def __init__(self, templates_dir: str = "app/templates/emails"):
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        self.env.filters['format_datetime'] = self._format_datetime_filter
    
    def _format_datetime_filter(self, dt, format_string='%Y-%m-%d %H:%M'):
        if dt is None:
            return ""
        return dt.strftime(format_string)
    
    def render_template(
        self,
        template_name: str,
        context: Dict[str, Any],
        language: str = "he"
    ) -> tuple[str, str]:
        """
        Render email template to text and HTML.
        
        Returns:
            (text_body, html_body)
        """
        context.update({
            'language': language,
            'app_name': settings.APP_NAME,
            'support_email': settings.EMAILS_FROM_EMAIL,
        })
        
        # Render HTML template
        html_template = self.env.get_template(f"{template_name}.html")
        html_body = html_template.render(**context)
        
        # Render text template or strip HTML
        try:
            text_template = self.env.get_template(f"{template_name}.txt")
            text_body = text_template.render(**context)
        except:
            import re
            text_body = re.sub('<[^<]+?>', '', html_body)
        
        return text_body, html_body
```

---

### ✅ 18.2 – SMTP Email Sending

**למה זה שימושי:** שליחת מיילים עם retry ו-error handling

```python
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

async def send_email(
    to_address: str,
    subject: str,
    body_html: str,
    body_text: str
) -> bool:
    """Send email via SMTP."""
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = settings.EMAILS_FROM_EMAIL
        msg['To'] = to_address
        msg['Subject'] = subject
        
        # Add text and HTML parts
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        
        # Connect to SMTP server
        if settings.SMTP_TLS:
            context = ssl.create_default_context()
            smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            smtp.starttls(context=context)
        else:
            smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        
        # Authenticate
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        
        # Send email
        smtp.send_message(msg)
        smtp.quit()
        
        logger.info("Email sent successfully", to=to_address, subject=subject)
        return True
    
    except Exception as e:
        logger.error("Failed to send email", to=to_address, error=str(e))
        return False
```

---

## 19.x – Configuration ו-Settings

### ✅ 19.1 – Pydantic Settings עם Environment Variables

**למה זה שימושי:** ניהול הגדרות עם validation אוטומטי

```python
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # App metadata
    APP_NAME: str = "Animal Rescue Bot"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    
    # Database
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DB: str = Field(default="animal_rescue")
    POSTGRES_USER: str = Field(default="postgres")
    POSTGRES_PASSWORD: str = Field(description="Database password")
    
    DATABASE_URL: Optional[str] = None
    
    @model_validator(mode='after')
    def assemble_database_url(self) -> 'Settings':
        """Build DATABASE_URL from components."""
        if not self.DATABASE_URL:
            url = (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
            object.__setattr__(self, "DATABASE_URL", url)
        return self
    
    # Redis
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: Optional[str] = None
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = Field(description="Bot token from @BotFather")
    
    # Feature flags
    ENABLE_WORKERS: bool = Field(default=False)
    ENABLE_EMAIL_ALERTS: bool = Field(default=False)
    
    # Computed properties
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }

# Create cached settings instance
@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

---

## 20.x – NLP ו-Text Analysis

### ✅ 20.1 – Keyword Extraction

**למה זה שימושי:** חילוץ מילות מפתח מטקסט בעברית/ערבית/אנגלית

```python
from collections import Counter
import re

class KeywordExtractor:
    """Extract keywords from text."""
    
    def __init__(self):
        self.stop_words = {
            "he": {"של", "את", "על", "עם", "לא", "זה", "היה", "הוא", "היא"},
            "ar": {"في", "من", "إلى", "على", "هذا", "هذه"},
            "en": {"the", "and", "or", "but", "in", "on", "at", "to", "for"}
        }
    
    def extract_keywords(self, text: str, language: str = "he", top_n: int = 10) -> List[str]:
        """
        Extract top keywords from text.
        
        Example:
            extractor = KeywordExtractor()
            keywords = extractor.extract_keywords("כלב פצוע בכביש", language="he")
        """
        # Extract words
        words = re.findall(r'\b\w+\b', text.lower())
        
        # Filter stop words and short words
        stop_words = self.stop_words.get(language, set())
        filtered = [
            word for word in words
            if len(word) > 2 and word not in stop_words and not word.isdigit()
        ]
        
        # Count and return most common
        word_counts = Counter(filtered)
        return [word for word, count in word_counts.most_common(top_n)]
```

---

### ✅ 20.2 – Language Detection

**למה זה שימושי:** זיהוי אוטומטי של שפת טקסט

```python
class LanguageDetector:
    """Detect language from text content."""
    
    # Character ranges
    HEBREW_CHARS = set(range(0x0590, 0x05FF + 1))
    ARABIC_CHARS = set(range(0x0600, 0x06FF + 1))
    
    def detect_language(self, text: str) -> Tuple[str, float]:
        """
        Detect language from text.
        
        Returns:
            (language_code, confidence)
        
        Example:
            detector = LanguageDetector()
            lang, confidence = detector.detect_language("שלום עולם")
            # Returns: ("he", 0.95)
        """
        if not text.strip():
            return "he", 0.0
        
        # Count character types
        hebrew_chars = sum(1 for char in text if ord(char) in self.HEBREW_CHARS)
        arabic_chars = sum(1 for char in text if ord(char) in self.ARABIC_CHARS)
        total_chars = len([c for c in text if c.isalpha()])
        
        if total_chars == 0:
            return "he", 0.0
        
        hebrew_ratio = hebrew_chars / total_chars
        arabic_ratio = arabic_chars / total_chars
        
        # Determine language
        if hebrew_ratio > 0.3:
            return "he", min(1.0, hebrew_ratio + 0.2)
        elif arabic_ratio > 0.3:
            return "ar", min(1.0, arabic_ratio + 0.2)
        else:
            return "en", 0.5
```

---

## 📌 סיכום

זהו אוסף של **20 סניפטים חדשים** שמשלימים את ספריית Code Keeper המקורית.

הסניפטים מכסים:
- ✅ Background Jobs עם RQ
- ✅ Telegram Bot Setup ו-Webhooks
- ✅ Database Async Patterns
- ✅ Error Handling ו-Exceptions
- ✅ Structured Logging
- ✅ File Storage ו-Validation
- ✅ JWT Authentication
- ✅ Redis ו-Distributed Locks
- ✅ Health Checks
- ✅ Email Templates
- ✅ Configuration Management
- ✅ NLP ו-Language Detection

כל הסניפטים נלקחו מקוד אמיתי עובד בפרויקט ונבדקו בייצור.
