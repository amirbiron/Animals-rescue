# מדריך למפתחים 👨‍💻

מדריך מקיף לפיתוח והרחבת המערכת, כולל מבנה הקוד, כללי כתיבה, בדיקות ותרומה לפרויקט.

## מבנה הפרויקט 📁

```
animal-rescue-bot/
├── app/                      # קוד האפליקציה
│   ├── api/                  # REST API endpoints
│   │   └── v1/              
│   │       ├── reports.py    # נתיבי דיווחים
│   │       ├── api.py        # נתיבים כלליים
│   │       └── twilio_webhook.py
│   ├── bot/                  # לוגיקת הבוט
│   │   ├── handlers.py       # טיפול בפקודות
│   │   └── webhook.py        # קבלת webhooks
│   ├── core/                 # פונקציונליות ליבה
│   │   ├── config.py         # קונפיגורציה
│   │   ├── security.py       # אבטחה ואימות
│   │   ├── i18n.py          # תמיכה רב-לשונית
│   │   └── cache.py         # ניהול cache
│   ├── models/              # מודלים ו-DB
│   │   └── database.py      # SQLAlchemy models
│   ├── services/            # שירותים חיצוניים
│   │   ├── google.py        # Google APIs
│   │   ├── whatsapp.py      # WhatsApp/Twilio
│   │   ├── nlp.py           # עיבוד שפה
│   │   └── email.py         # שליחת מיילים
│   ├── workers/             # משימות רקע
│   │   ├── jobs.py          # הגדרת משימות
│   │   └── manager.py       # ניהול workers
│   ├── templates/           # תבניות HTML/Email
│   ├── translations/        # קבצי תרגום
│   └── main.py             # נקודת כניסה
├── tests/                   # בדיקות
├── scripts/                 # סקריפטים
├── docs/                    # תיעוד
└── requirements.txt         # תלויות
```

## סביבת פיתוח 🛠️

### הגדרת סביבה מקומית

```bash
# Clone ויצירת venv
git clone https://github.com/animal-rescue-bot/animal-rescue-bot.git
cd animal-rescue-bot
python3.12 -m venv venv
source venv/bin/activate

# התקנת תלויות פיתוח
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Pre-commit hooks
pre-commit install
```

### כלי פיתוח מומלצים

| כלי | מטרה | התקנה |
|-----|------|--------|
| **Black** | פורמט קוד | `pip install black` |
| **Ruff** | Linting מהיר | `pip install ruff` |
| **MyPy** | Type checking | `pip install mypy` |
| **Pytest** | בדיקות | `pip install pytest` |
| **IPython** | REPL משופר | `pip install ipython` |

### VS Code Settings

```json
{
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "black",
    "python.testing.pytestEnabled": true,
    "editor.formatOnSave": true,
    "[python]": {
        "editor.codeActionsOnSave": {
            "source.organizeImports": true
        }
    }
}
```

## כללי כתיבת קוד 📝

### Python Style Guide

```python
# ✅ נכון - Type hints, docstrings, async/await
from typing import Optional, List
from datetime import datetime

async def process_report(
    report_id: str,
    urgent: bool = False,
    tags: Optional[List[str]] = None
) -> dict:
    """
    Process a new animal rescue report.
    
    Args:
        report_id: Unique identifier for the report
        urgent: Whether this is an urgent case
        tags: Optional list of tags to categorize the report
        
    Returns:
        Dictionary containing processing results
        
    Raises:
        ReportNotFoundError: If report_id doesn't exist
        ProcessingError: If processing fails
    """
    if tags is None:
        tags = []
        
    # Use meaningful variable names
    report = await fetch_report(report_id)
    
    # Early return for edge cases
    if not report:
        raise ReportNotFoundError(f"Report {report_id} not found")
    
    # Process with context manager
    async with processing_lock(report_id):
        result = await _process_internal(report, urgent, tags)
        
    return result
```

### קונבנציות נוספות

```python
# Constants - UPPER_CASE
MAX_RETRY_ATTEMPTS = 3
DEFAULT_TIMEOUT = 30

# Private functions - underscore prefix
def _internal_helper():
    pass

# Class names - PascalCase
class AnimalReport:
    pass

# Module level - snake_case
def calculate_distance():
    pass

# Async functions - prefix with async_/await_
async def async_fetch_data():
    pass
```

## עבודה עם מסד הנתונים 🗄️

### הגדרת מודלים

```python
# app/models/database.py
from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import uuid

Base = declarative_base()

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    description = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    status = Column(String, default="open")
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    notifications = relationship("Notification", back_populates="report")
    
    # Indexes
    __table_args__ = (
        Index("idx_reports_status", "status"),
        Index("idx_reports_location", "lat", "lon"),
    )
    
    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": str(self.id),
            "description": self.description,
            "location": {"lat": self.lat, "lon": self.lon},
            "status": self.status,
            "created_at": self.created_at.isoformat()
        }
```

### מיגרציות עם Alembic

```bash
# יצירת מיגרציה חדשה
alembic revision --autogenerate -m "Add organization_type field"

# בדיקת המיגרציה
alembic show

# החלת מיגרציה
alembic upgrade head

# חזרה אחורה
alembic downgrade -1
```

### שאילתות מתקדמות

```python
# שימוש ב-async SQLAlchemy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

async def get_nearby_reports(
    session: AsyncSession,
    lat: float,
    lon: float,
    radius_km: float = 10
) -> List[Report]:
    """Get reports within radius using PostGIS."""
    
    # Haversine formula for distance
    query = select(Report).where(
        and_(
            Report.status == "open",
            func.ST_DWithin(
                func.ST_MakePoint(Report.lon, Report.lat),
                func.ST_MakePoint(lon, lat),
                radius_km * 1000  # Convert to meters
            )
        )
    ).order_by(
        func.ST_Distance(
            func.ST_MakePoint(Report.lon, Report.lat),
            func.ST_MakePoint(lon, lat)
        )
    )
    
    result = await session.execute(query)
    return result.scalars().all()
```

## תמיכה בשפות (i18n) 🌍

### הוספת שפה חדשה

1. **יצירת קובץ תרגום**
```json
// app/translations/ru.json
{
    "welcome": "Добро пожаловать в бот спасения животных!",
    "new_report": "Новый отчет",
    "choose_animal": "Выберите тип животного",
    "dog": "Собака",
    "cat": "Кошка",
    "bird": "Птица",
    "other": "Другое",
    "send_photo": "Пожалуйста, отправьте фото",
    "send_location": "Отправьте местоположение",
    "report_received": "Отчет получен! ID: {report_id}"
}
```

2. **עדכון קונפיגורציה**
```python
# app/core/i18n.py
SUPPORTED_LANGUAGES = {
    "he": "עברית",
    "en": "English",
    "ar": "العربية",
    "ru": "Русский"  # חדש!
}

# זיהוי שפה אוטומטי
def detect_language(text: str) -> str:
    """Detect language from text."""
    if any('\u0400' <= char <= '\u04FF' for char in text):
        return "ru"  # Cyrillic
    # ... בדיקות נוספות
```

3. **שימוש בתרגומים**
```python
from app.core.i18n import get_text

async def handle_start(update, context):
    user_lang = context.user_data.get("language", "he")
    welcome_text = get_text("welcome", user_lang)
    await update.message.reply_text(welcome_text)
```

## כתיבת בדיקות 🧪

### מבנה בדיקות

```python
# tests/test_report_flow.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
async def test_client():
    """Create test client."""
    from app.main import app
    from httpx import AsyncClient
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def mock_telegram():
    """Mock Telegram bot."""
    with patch("app.bot.handlers.bot") as mock:
        mock.send_message = AsyncMock()
        yield mock

class TestReportFlow:
    """Test complete report flow."""
    
    @pytest.mark.asyncio
    async def test_create_report_success(self, test_client, mock_telegram):
        """Test successful report creation."""
        # Arrange
        report_data = {
            "description": "כלב פצוע ברחוב הרצל",
            "lat": 32.0853,
            "lon": 34.7818,
            "urgency": "high",
            "animal_type": "dog"
        }
        
        # Act
        response = await test_client.post("/api/v1/reports/", json=report_data)
        
        # Assert
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["status"] == "open"
        
        # Verify notification sent
        mock_telegram.send_message.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_report_validation(self, test_client):
        """Test report validation."""
        # Missing required fields
        invalid_data = {"description": "test"}
        
        response = await test_client.post("/api/v1/reports/", json=invalid_data)
        
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(e["loc"] == ["body", "lat"] for e in errors)
```

### בדיקות אינטגרציה

```python
# tests/test_integration.py
import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

@pytest.fixture(scope="session")
def postgres():
    """Start PostgreSQL container for tests."""
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres

@pytest.fixture(scope="session")
def redis():
    """Start Redis container for tests."""
    with RedisContainer("redis:7-alpine") as redis:
        yield redis

@pytest.mark.integration
async def test_full_flow_with_db(postgres, redis):
    """Test complete flow with real databases."""
    # Setup test environment
    os.environ["DATABASE_URL"] = postgres.get_connection_url()
    os.environ["REDIS_URL"] = redis.get_connection_url()
    
    # Run migrations
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    
    # Test flow
    report = await create_report(...)
    assert report.id is not None
    
    # Cleanup
    command.downgrade(alembic_cfg, "base")
```

### Coverage

```bash
# הרצת בדיקות עם כיסוי
pytest --cov=app --cov-report=html tests/

# פתיחת דוח הכיסוי
open htmlcov/index.html

# דרישות כיסוי מינימליות
# - Core logic: 90%
# - API endpoints: 85%
# - Services: 80%
# - Overall: 85%
```

## הוספת פיצ'רים חדשים 🚀

### דוגמה: הוספת תמיכה בווידאו

#### 1. עדכון המודל
```python
# app/models/database.py
class Report(Base):
    # ... existing fields ...
    video_url = Column(String, nullable=True)
    video_thumbnail = Column(String, nullable=True)
```

#### 2. הוספת handler לבוט
```python
# app/bot/handlers.py
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video uploads."""
    video = update.message.video
    
    # Download video
    file = await video.get_file()
    video_path = f"uploads/videos/{video.file_id}.mp4"
    await file.download_to_drive(video_path)
    
    # Generate thumbnail
    thumbnail = await generate_video_thumbnail(video_path)
    
    # Store in context
    context.user_data["video_url"] = video_path
    context.user_data["video_thumbnail"] = thumbnail
    
    await update.message.reply_text("וידאו התקבל! 📹")
    return NEXT_STATE
```

#### 3. עדכון ה-API
```python
# app/api/v1/reports.py
class ReportCreate(BaseModel):
    # ... existing fields ...
    video_url: Optional[str] = None
    video_thumbnail: Optional[str] = None

@router.post("/reports/")
async def create_report(report: ReportCreate):
    # Process video if provided
    if report.video_url:
        await process_video(report.video_url)
    # ... rest of logic
```

#### 4. הוספת בדיקות
```python
# tests/test_video_support.py
async def test_video_upload():
    with open("tests/fixtures/sample.mp4", "rb") as video:
        response = await client.post(
            "/api/v1/reports/",
            files={"video": video}
        )
    assert response.status_code == 201
    assert "video_url" in response.json()
```

## עבודה עם Workers 🔧

### יצירת Job חדש

```python
# app/workers/jobs.py
from rq import get_current_job
from app.services.ai import analyze_image

@job("default", timeout=300, result_ttl=3600)
async def analyze_report_images(report_id: str):
    """Analyze images using AI."""
    job = get_current_job()
    
    # Update job progress
    job.meta["progress"] = 0
    job.save_meta()
    
    # Fetch report
    report = await get_report(report_id)
    
    # Analyze each image
    results = []
    for i, image_url in enumerate(report.images):
        result = await analyze_image(image_url)
        results.append(result)
        
        # Update progress
        job.meta["progress"] = (i + 1) / len(report.images) * 100
        job.save_meta()
    
    # Save results
    await update_report(report_id, {"ai_analysis": results})
    
    return {"status": "completed", "results": results}
```

### ניהול תורים

```python
# app/workers/manager.py
from rq import Queue
from redis import Redis

class QueueManager:
    def __init__(self):
        self.redis = Redis.from_url(REDIS_URL)
        self.queues = {
            "default": Queue("default", connection=self.redis),
            "alerts": Queue("alerts", connection=self.redis),
            "maintenance": Queue("maintenance", connection=self.redis)
        }
    
    def enqueue_job(self, queue_name: str, func, *args, **kwargs):
        """Enqueue a job to specific queue."""
        queue = self.queues[queue_name]
        job = queue.enqueue(func, *args, **kwargs)
        return job.id
    
    def get_job_status(self, job_id: str):
        """Get job status and progress."""
        from rq.job import Job
        job = Job.fetch(job_id, connection=self.redis)
        return {
            "id": job.id,
            "status": job.get_status(),
            "progress": job.meta.get("progress", 0),
            "result": job.result
        }
```

## Performance Optimization 🚄

### Caching Strategy

```python
# app/core/cache.py
from functools import wraps
import hashlib
import json

def cache_result(ttl: int = 300):
    """Cache function results decorator."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{func.__name__}:{hashlib.md5(
                json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True).encode()
            ).hexdigest()}"
            
            # Try to get from cache
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await redis_client.setex(
                cache_key,
                ttl,
                json.dumps(result)
            )
            
            return result
        return wrapper
    return decorator

# Usage
@cache_result(ttl=3600)
async def get_organization_stats(org_id: str):
    """Get organization statistics (cached for 1 hour)."""
    # Heavy computation...
    return stats
```

### Database Query Optimization

```python
# Use select_related / joinedload for relationships
from sqlalchemy.orm import selectinload

async def get_reports_with_notifications():
    """Fetch reports with notifications in single query."""
    query = select(Report).options(
        selectinload(Report.notifications)
    ).where(
        Report.status == "open"
    )
    
    result = await session.execute(query)
    return result.scalars().all()

# Use bulk operations
async def bulk_update_status(report_ids: List[str], status: str):
    """Update multiple reports efficiently."""
    await session.execute(
        update(Report).where(
            Report.id.in_(report_ids)
        ).values(status=status)
    )
    await session.commit()
```

## Debugging Tips 🐛

### Logging

```python
# app/core/logging.py
import structlog

logger = structlog.get_logger()

# Rich logging with context
logger.info(
    "report_created",
    report_id=report.id,
    user_id=user.id,
    location={"lat": lat, "lon": lon},
    duration_ms=elapsed_time
)

# Error logging with traceback
try:
    await process_report(report)
except Exception as e:
    logger.error(
        "report_processing_failed",
        report_id=report.id,
        error=str(e),
        exc_info=True
    )
```

### Profiling

```python
# Memory profiling
from memory_profiler import profile

@profile
def memory_intensive_function():
    # Your code here
    pass

# Time profiling
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()
# Your code
profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats(10)
```

### Debug Mode

```python
# app/core/config.py
if DEBUG:
    # Enable SQL query logging
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    
    # Add debug endpoints
    @app.get("/debug/config")
    async def debug_config():
        return {k: v for k, v in os.environ.items() if not k.startswith("SECRET")}
    
    # Enable detailed error messages
    app.add_exception_handler(
        Exception,
        lambda request, exc: JSONResponse(
            status_code=500,
            content={"error": str(exc), "traceback": traceback.format_exc()}
        )
    )
```

## Git Workflow 🌳

### Branch Strategy

```bash
main
├── develop
│   ├── feature/add-video-support
│   ├── feature/improve-nlp
│   └── feature/dashboard-v2
├── hotfix/critical-bug-fix
└── release/v2.0.0
```

### Commit Messages

```bash
# Format: <type>(<scope>): <subject>

feat(bot): add video upload support
fix(api): handle null location gracefully
docs(readme): update installation instructions
test(reports): add integration tests
refactor(db): optimize query performance
style(code): apply black formatting
chore(deps): update dependencies
```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

## CI/CD Pipeline 🔄

### GitHub Actions

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
          
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.12'
        
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
        
    - name: Lint with ruff
      run: ruff check app/
      
    - name: Type check with mypy
      run: mypy app/
      
    - name: Test with pytest
      run: pytest --cov=app --cov-report=xml
      
    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## Security Best Practices 🔒

### Input Validation

```python
from pydantic import BaseModel, validator, Field
from typing import Optional
import re

class ReportCreate(BaseModel):
    description: str = Field(..., min_length=10, max_length=1000)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    phone: Optional[str] = None
    
    @validator("phone")
    def validate_phone(cls, v):
        if v and not re.match(r"^\+?[1-9]\d{1,14}$", v):
            raise ValueError("Invalid phone number format")
        return v
    
    @validator("description")
    def sanitize_description(cls, v):
        # Remove potential XSS
        import bleach
        return bleach.clean(v, strip=True)
```

### API Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/reports/")
@limiter.limit("10/minute")
async def create_report(request: Request, report: ReportCreate):
    # Your code
    pass
```

## תרומה לפרויקט 🤝

### Setup למתחילים

1. Fork הפרויקט
2. Clone המאגר שלך
3. הוסף את המקור כ-upstream
```bash
git remote add upstream https://github.com/animal-rescue-bot/animal-rescue-bot.git
```

### יצירת Feature

```bash
# עדכון מ-upstream
git fetch upstream
git checkout develop
git merge upstream/develop

# יצירת branch חדש
git checkout -b feature/amazing-feature

# עבודה על הפיצ'ר
# ... code changes ...

# Commit
git add .
git commit -m "feat: add amazing feature"

# Push
git push origin feature/amazing-feature

# יצירת Pull Request ב-GitHub
```

### Code Review Checklist

- [ ] הקוד עוקב אחר הסגנון של הפרויקט
- [ ] יש בדיקות לפונקציונליות החדשה
- [ ] התיעוד עודכן
- [ ] אין קוד מיותר או מוערות
- [ ] Performance לא נפגע
- [ ] Security best practices

## משאבים נוספים 📚

### תיעוד רלוונטי
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/)
- [python-telegram-bot](https://python-telegram-bot.org/)
- [Redis Documentation](https://redis.io/docs/)

### כלים מועילים
- [Postman](https://www.postman.com/) - בדיקת API
- [DBeaver](https://dbeaver.io/) - ניהול DB
- [RedisInsight](https://redis.com/redis-enterprise/redis-insight/) - ניהול Redis
- [ngrok](https://ngrok.com/) - Tunneling לפיתוח

### קהילה
- [Discord Server](https://discord.gg/animal-rescue)
- [Stack Overflow Tag](https://stackoverflow.com/questions/tagged/animal-rescue-bot)
- [GitHub Discussions](https://github.com/animal-rescue-bot/discussions)

---

<div align="center">
  <strong>💪 Happy Coding! יחד נציל חיים</strong>
</div>