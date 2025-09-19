# ARCHITECTURE

## תקציר

**Animal Rescue Bot** - מערכת דיווח והתראות לחילוץ בעלי חיים. המערכת מאפשרת למשתמשים לדווח דרך בוט טלגרם על בעלי חיים הזקוקים לעזרה, מעבדת את הדיווחים ושולחת התראות אוטומטיות לארגונים רלוונטיים באזור.

### רכיבי ליבה (כפי שקיימים בפועל)
- **Bot** - בוט טלגרם לקבלת דיווחים מהציבור
- **API** - FastAPI REST API לניהול דיווחים וארגונים
- **Workers** - RQ workers לעיבוד אסינכרוני ושליחת התראות
- **DB** - PostgreSQL עם SQLAlchemy ORM (async) ו-GeoAlchemy2 לתמיכה ב-GIS
- **Redis** - מטמון, rate limiting, ותורי משימות
- **Storage** - מערכת אחסון קבצים (local/S3/R2)

## סטאק ותלויות

### גרסת Python
- Python 3.12+ (מוזכר ב-main.py)

### ספריות עיקריות שזוהו
- **FastAPI** (0.115.6) - Framework אסינכרוני לבניית APIs
- **python-telegram-bot** (22.4) - ספריית Telegram Bot עם תמיכת webhooks
- **SQLAlchemy** (2.0.43) - ORM אסינכרוני
- **asyncpg** (0.30.0) - PostgreSQL driver אסינכרוני
- **Redis** (6.4.0) - Redis client עם hiredis
- **RQ** (2.0.0) - תורי משימות פשוטים
- **Pydantic** (2.10.4) - Data validation
- **spaCy** (3.8.2) - NLP עם מודל עברית
- **boto3** (1.35.84) - AWS S3/R2 storage
- **googlemaps** (4.10.0) - Google Places/Geocoding APIs
- **structlog** (24.5.0) - Structured logging
- **Sentry** (2.21.0) - Error tracking
- **Prometheus** (0.22.0) - Metrics collection

### שירותי צד ג' שנמצאים בשימוש בקוד
- **Telegram Bot API** - בוט טלגרם
- **Google Places API** - חיפוש ארגונים וטרינריים
- **Google Geocoding API** - המרת כתובות לקואורדינטות
- **S3/R2** - אחסון קבצים (אופציונלי)
- **Email (SMTP)** - שליחת התראות במייל

## עץ תיקיות

```
/workspace/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── api/
│   │   └── v1/
│   │       ├── api.py          # Main API router aggregator
│   │       └── reports.py      # Reports CRUD endpoints
│   ├── bot/
│   │   ├── handlers.py         # Telegram bot message handlers
│   │   └── webhook.py          # Telegram webhook router
│   ├── core/
│   │   ├── cache.py           # Redis cache and rate limiting
│   │   ├── config.py          # Settings management (Pydantic)
│   │   └── security.py        # JWT auth and permissions
│   ├── models/
│   │   └── databas.py         # SQLAlchemy models (typo in filename)
│   ├── services/
│   │   ├── file_storage.py    # File storage abstraction
│   │   ├── google.py          # Google APIs integration
│   │   └── nlp.py             # NLP text analysis
│   └── workers/
│       └── jobs.py            # Background jobs (RQ)
├── requirements.txt           # Python dependencies
└── README.md                 # Basic documentation
```

## מודולים וממשקים

### app/main.py
**תפקיד**: Entry point של FastAPI, middleware, health checks
- `create_app()` - Application factory
- `lifespan()` - Startup/shutdown management
- `health_check()` - בדיקת בריאות המערכת
- `metrics()` - Prometheus metrics endpoint
- Middleware: CORS, Rate limiting, Request logging, Error handling

### app/api/v1/api.py
**תפקיד**: API router aggregator
- `api_router` - Main router instance
- `/health` - API health check
- `/info` - API information

### app/api/v1/reports.py
**תפקיד**: Reports REST API endpoints
- `create_report()` - POST /reports
- `get_report()` - GET /reports/{report_id}
- `update_report()` - PUT /reports/{report_id}
- `delete_report()` - DELETE /reports/{report_id}
- `list_reports()` - GET /reports
- `upload_report_file()` - POST /reports/{report_id}/files
- `update_report_status()` - POST /reports/{report_id}/status
- `get_reports_summary()` - GET /reports/stats/summary

### app/bot/handlers.py
**תפקיד**: Telegram bot conversation handlers
- `start_command()` - /start command
- `help_command()` - /help command
- `status_command()` - /status command
- `start_report_creation()` - Begin report flow
- `handle_photo_upload()` - Process photos
- `handle_location()` - Process location
- `handle_description()` - Process description
- `submit_report()` - Final submission
- `create_report_conversation_handler()` - ConversationHandler setup

### app/bot/webhook.py
**תפקיד**: Telegram webhook HTTP endpoints
- `telegram_webhook()` - POST /telegram/webhook
- `webhook_info()` - GET /telegram/webhook/info
- `set_webhook()` - POST /telegram/webhook/set
- `delete_webhook()` - DELETE /telegram/webhook

### app/core/config.py
**תפקיד**: Configuration management
- `Settings` - Pydantic settings class
- `get_settings()` - Cached settings instance
- `setup_logging()` - Logging configuration
- Environment variables validation

### app/core/cache.py
**תפקיד**: Redis cache and rate limiting
- `CacheManager` - Advanced caching with tags
- `RateLimiter` - Multiple rate limiting algorithms
- `DistributedLock` - Distributed locking
- `SessionManager` - Session storage
- `check_rate_limit()` - Rate limit checker
- `@cached` - Cache decorator

### app/core/security.py
**תפקיד**: Authentication and authorization
- `create_access_token()` - JWT token creation
- `decode_token()` - Token validation
- `get_current_user()` - Current user dependency
- `require_authentication()` - Auth requirement
- `require_roles()` - Role-based access control
- `authenticate_telegram_user()` - Telegram auth

### app/models/databas.py
**תפקיד**: Database models and ORM
- `User` - משתמשים
- `Organization` - ארגונים
- `Report` - דיווחים
- `ReportFile` - קבצים מצורפים
- `Alert` - התראות
- `Event` - אירועי audit
- Enums: `UserRole`, `ReportStatus`, `UrgencyLevel`, `AnimalType`, etc.
- `get_db_session()` - Database session dependency
- `create_tables()`, `drop_tables()` - Schema management

### app/services/file_storage.py
**תפקיד**: File storage abstraction (TODO - קובץ מיובא אך לא קיים)

### app/services/google.py
**תפקיד**: Google APIs integration (TODO - קובץ מיובא אך לא קיים)
- `GoogleService` - Places & Geocoding APIs

### app/services/nlp.py
**תפקיד**: NLP text analysis (TODO - קובץ מיובא אך לא קיים)
- `NLPService` - Text analysis with spaCy

### app/workers/jobs.py
**תפקיד**: Background jobs with RQ
- `process_new_report()` - Process new submissions
- `send_organization_alert()` - Send alerts
- `retry_failed_alerts()` - Retry mechanism
- `cleanup_old_data()` - Data retention
- `update_organization_stats()` - Statistics update
- `sync_google_places_data()` - External API sync
- `generate_daily_statistics()` - Daily reports
- `schedule_recurring_jobs()` - Job scheduling

### app/admin/routes.py
**תפקיד**: Admin interface routes (TODO - מיובא אך לא קיים)

### app/core/exceptions.py
**תפקיד**: Custom exceptions (TODO - מיובא אך לא קיים)

### app/core/i18n.py
**תפקיד**: Internationalization (TODO - מיובא אך לא קיים)

### app/core/rate_limit.py
**תפקיד**: Rate limiting (TODO - חלק מ-cache.py כעת)

### app/services/email.py
**תפקיד**: Email service (TODO - מיובא אך לא קיים)

### app/services/telegram_alerts.py
**תפקיד**: Telegram alerts service (TODO - מיובא אך לא קיים)

### app/services/geocoding.py
**תפקיד**: Geocoding service (TODO - מיובא אך לא קיים)

### app/workers/manager.py
**תפקיד**: Workers management (TODO - מיובא אך לא קיים)

### app/bot/bot.py
**תפקיד**: Bot instance (TODO - מיובא אך לא קיים)

### app/templates/alerts/
**תפקיד**: Alert message templates (TODO - מוזכר אך לא קיים)

## מודל נתונים

### טבלאות עיקריות

**users**
- id (UUID PK)
- telegram_user_id (Integer, unique)
- username, email, phone
- role (Enum: reporter/org_staff/org_admin/system_admin)
- trust_score (Float 0-10)
- organization_id (FK)

**organizations**
- id (UUID PK)
- name, description
- organization_type (Enum)
- location (PostGIS POINT)
- latitude, longitude
- service_radius_km
- alert_channels (Array)
- telegram_chat_id

**reports**
- id (UUID PK)
- public_id (String, unique)
- reporter_id (FK users)
- title, description
- animal_type, urgency_level, status (Enums)
- location (PostGIS POINT)
- latitude, longitude, address
- keywords (Array)
- sentiment_score
- assigned_organization_id (FK)

**report_files**
- id (UUID PK)
- report_id (FK reports)
- filename, file_type, mime_type
- storage_backend, storage_path
- width, height (for images)

**alerts**
- id (UUID PK)
- report_id (FK reports)
- organization_id (FK organizations)
- channel (Enum: telegram/email/sms)
- recipient, message
- status (Enum)
- attempts, max_attempts

**events**
- id (UUID PK)
- event_type (Enum)
- entity_type, entity_id
- payload (JSONB)
- processed (Boolean)

### Enums עיקריים
- UserRole: reporter, org_staff, org_admin, system_admin
- ReportStatus: draft, submitted, pending, acknowledged, in_progress, resolved, closed
- UrgencyLevel: low, medium, high, critical
- AnimalType: dog, cat, bird, wildlife, exotic, livestock, other
- AlertChannel: telegram, email, sms, whatsapp, webhook

## נקודות API

### Reports API (prefix: /api/v1/reports)
- `POST /` - Create new report
- `GET /` - List reports with filters
- `GET /{report_id}` - Get specific report
- `PUT /{report_id}` - Update report
- `DELETE /{report_id}` - Delete report (admin)
- `POST /{report_id}/files` - Upload file
- `POST /{report_id}/status` - Update status
- `GET /stats/summary` - Statistics

### Telegram Webhook (prefix: /telegram)
- `POST /webhook` - Receive Telegram updates
- `GET /webhook/info` - Webhook information
- `POST /webhook/set` - Set webhook
- `DELETE /webhook` - Delete webhook

### System Endpoints
- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics
- `GET /version` - Version info

### Admin Interface (prefix: /admin)
TODO - מוזכר אך לא מיושם

## Jobs/Workers ותורים

### RQ Workers עם Redis (DB 1)

**Default Queue**
- `process_new_report` - עיבוד דיווח חדש
- `send_test_alert` - התראת בדיקה

**Alerts Queue**
- `send_organization_alert` - שליחת התראה לארגון
- `retry_failed_alerts` - ניסיון חוזר להתראות שנכשלו

**Maintenance Queue**
- `cleanup_old_data` - ניקוי נתונים ישנים
- `update_organization_stats` - עדכון סטטיסטיקות
- `generate_daily_statistics` - סטטיסטיקות יומיות

**External Queue**
- `sync_google_places_data` - סנכרון עם Google Places

### Scheduled Jobs (RQ Scheduler)
- Daily cleanup at 2 AM
- Organization stats every 6 hours
- Google Places sync weekly (Sunday 3 AM)
- Daily statistics at midnight
- Retry failed alerts every 15 minutes

## קונפיגורציה ו-ENV

### משתני סביבה נדרשים (מ-config.py)

**Core**
- `SECRET_KEY` - JWT secret
- `ENVIRONMENT` - development/testing/staging/production
- `DEBUG` - Debug mode

**Database**
- `POSTGRES_HOST`, `POSTGRES_PORT`
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`

**Redis**
- `REDIS_HOST`, `REDIS_PORT`
- `REDIS_PASSWORD` (optional)

**Telegram**
- `TELEGRAM_BOT_TOKEN` - Bot token (required)
- `TELEGRAM_WEBHOOK_SECRET` - Webhook security
- `WEBHOOK_HOST` - Public host for webhook

**External APIs**
- `GOOGLE_PLACES_API_KEY`
- `GOOGLE_GEOCODING_API_KEY`

**Storage (for S3/R2)**
- `S3_ENDPOINT_URL`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_BUCKET_NAME`

**Email**
- `SMTP_HOST`, `SMTP_PORT`
- `SMTP_USER`, `SMTP_PASSWORD`

**Monitoring**
- `SENTRY_DSN` - Error tracking

### קבצי קונפיג
TODO - לא נמצאו Dockerfile, render.yaml או docker-compose.yml

## פריסה והרצה

### הרצה לוקאלית

**Development**
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Production**
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### פריסה
TODO - אין קבצי deployment (Docker/render.yaml)

### Health Checks
- `GET /health` - בדיקת בריאות כללית (DB, Redis, Google APIs, Telegram)
- `GET /telegram/health` - בדיקת בוט טלגרם
- Per-service health status בתגובת /health

## תצפית וניטור

### Logging
- **structlog** - Structured JSON logging
- Log levels: INFO/WARNING/ERROR
- Request logging middleware
- Audit events בטבלת events

### Metrics
- **Prometheus** metrics ב-`/metrics`
- Counters: requests, reports, alerts, telegram messages
- Histograms: request duration
- Custom metrics per service

### Error Tracking
- **Sentry** integration (אם SENTRY_DSN מוגדר)

## i18n ואבטחה

### שפות
- Supported: he (עברית), ar (ערבית), en (English)
- Default: he
- Per-user language preference

### אבטחה
- JWT authentication
- Role-based access control (RBAC)
- Rate limiting (Redis-based)
- CORS configuration
- Security headers middleware
- Telegram webhook secret validation

## מגבלות ידועות ו-TODO

### קבצים חסרים (מיובאים אך לא קיימים)
- [ ] app/admin/routes.py - Admin interface
- [ ] app/bot/bot.py - Bot instance initialization
- [ ] app/core/exceptions.py - Custom exceptions
- [ ] app/core/i18n.py - Internationalization
- [ ] app/services/email.py - Email service
- [ ] app/services/file_storage.py - File storage
- [ ] app/services/geocoding.py - Geocoding service
- [ ] app/services/google.py - Google APIs
- [ ] app/services/nlp.py - NLP service
- [ ] app/services/telegram_alerts.py - Telegram alerts
- [ ] app/workers/manager.py - Worker management
- [ ] app/templates/alerts/ - Alert templates

### קבצי deployment חסרים
- [ ] Dockerfile
- [ ] docker-compose.yml
- [ ] render.yaml או כל קובץ deployment אחר
- [ ] .env.example

### תכונות לא מיושמות
- [ ] Organizations CRUD API
- [ ] Users management API
- [ ] Admin dashboard
- [ ] SMS alerts
- [ ] WhatsApp integration
- [ ] File cleanup job implementation
- [ ] Email templates

### בעיות פוטנציאליות
- שם קובץ databas.py במקום database.py (typo)
- חלק מה-imports מצביעים על קבצים לא קיימים
- אין migration files לדatabase
- אין unit tests או integration tests
- אין API documentation (OpenAPI/Swagger מופעל אך לא מלא)

## הערות

המערכת בנויה כ-microservices architecture עם הפרדה ברורה בין:
1. REST API לניהול נתונים
2. Telegram Bot לאינטראקציה עם משתמשים
3. Background workers לעיבוד אסינכרוני
4. External integrations (Google APIs, Storage)

המערכת תומכת ב-event-driven architecture עם audit trail מלא ומוכנה לscale עם Redis queues ו-async operations.