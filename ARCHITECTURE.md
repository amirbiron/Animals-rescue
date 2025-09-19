# ARCHITECTURE

## תקציר
בוט הצלת בעלי חיים - מערכת לדיווח והתראות מהיר על בעלי חיים במצוקה. המערכת מבוססת על FastAPI כשרת API, בוט טלגרם לאינטראקציה עם משתמשים, PostgreSQL לאחסון נתונים, Redis לקאש ותורים, ו-RQ לעיבוד משימות רקע.

רכיבי ליבה:
- **FastAPI Server** - שרת API עם endpoints לניהול דיווחים
- **Telegram Bot** - ממשק משתמש ראשי דרך טלגרם
- **Background Workers** - עובדי RQ לעיבוד משימות אסינכרוניות
- **PostgreSQL** - בסיס נתונים עם תמיכת GIS
- **Redis** - קאש ותורי משימות

## סטאק ותלויות
- **Python** - גרסה 3.12+ (לפי app/main.py:551)
- **FastAPI** (0.115.6) - Framework עבור API
- **python-telegram-bot** (22.4) - ספריית טלגרם עם webhook support
- **SQLAlchemy** (2.0.43) - ORM עם async support
- **asyncpg** (0.30.0) - PostgreSQL async driver
- **Redis** (6.4.0) + **RQ** (2.0.0) - תורי משימות
- **spaCy** (3.8.2) - NLP לעיבוד טקסט
- **googlemaps** (4.10.0) - Google Maps/Places API
- **boto3** (1.35.84) - S3/R2 storage
- **structlog** (24.5.0) - Structured logging
- **Sentry** (2.21.0) - Error tracking
- **prometheus-client** (0.22.0) - Metrics

## עץ תיקיות (סיכום)
```
/workspace/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── reports.py
│   ├── bot/
│   │   └── handlers.py
│   ├── core/
│   │   ├── cache.py
│   │   └── config.py
│   ├── models/
│   │   └── databas.py
│   ├── services/
│   │   ├── google.py
│   │   └── nlp.py
│   ├── workers/
│   │   └── jobs.py
│   └── main.py
├── requirements.txt
└── README.md
```

## מודולים וממשקים

### app.main
- תפקיד: נקודת כניסה ראשית של FastAPI
- נקודות כניסה:
  - `create_app() -> FastAPI` - Factory function
  - `lifespan(app)` - Lifecycle manager
- Middleware: CORS, GZip, Sessions, Rate limiting, Request logging
- Exception handlers לטיפול בשגיאות
- תלות: config, database, api.v1.api, bot.webhook, admin.routes

### app.core.config
- תפקיד: ניהול קונפיגורציה והגדרות
- נקודות כניסה:
  - `get_settings() -> Settings` - Cached settings instance
  - `setup_logging()` - Configure structured logging
- מחלקה: `Settings(BaseSettings)` - Pydantic settings עם ENV support
- תלות: אין

### app.core.cache
- תפקיד: ניהול Redis וקאש
- נקודות כניסה: TODO - קובץ לא נבדק במלואו
- תלות: config, exceptions

### app.models.databas
- תפקיד: מודלים של בסיס הנתונים (SQLAlchemy ORM)
- Enums:
  - `UserRole`: reporter, org_staff, org_admin, system_admin
  - `ReportStatus`: draft, submitted, pending, acknowledged, in_progress, resolved, closed, duplicate, invalid
  - `AnimalType`: dog, cat, bird, wildlife, exotic, livestock, other, unknown
  - `UrgencyLevel`: low, medium, high, critical
  - `OrganizationType`: vet_clinic, emergency_vet, animal_hospital, animal_shelter, rescue_org, government, volunteer_group
  - `AlertChannel`: telegram, email, sms, whatsapp, webhook
- טבלאות: User, Organization, Report, Alert, Event (TODO: פירוט מלא)
- תלות: config

### app.api.v1.reports
- תפקיד: REST API endpoints לניהול דיווחים
- נקודות כניסה (router endpoints):
  - `POST /` - יצירת דיווח חדש
  - `GET /{report_id}` - קבלת דיווח
  - `PUT /{report_id}` - עדכון דיווח
  - `DELETE /{report_id}` - מחיקת דיווח
  - `GET /` - רשימת דיווחים
  - `POST /{report_id}/files` - העלאת קבצים
  - `POST /{report_id}/status` - עדכון סטטוס
  - `GET /stats/summary` - סטטיסטיקות
- תלות: database, services (file_storage, geocoding, nlp), workers.jobs

### app.bot.handlers
- תפקיד: מטפלי הודעות של בוט טלגרם
- נקודות כניסה: ConversationHandlers, CommandHandlers, MessageHandlers
- תלות: database, services (nlp, geocoding, file_storage), workers.jobs, i18n

### app.services.google
- תפקיד: אינטגרציה עם Google APIs (Places, Geocoding)
- מחלקה: `GoogleService`
- תלות: config, cache, exceptions

### app.services.nlp
- תפקיד: עיבוד שפה טבעית עם spaCy
- מחלקה: `NLPService`
- תלות: config, cache

### app.workers.jobs
- תפקיד: משימות רקע עם RQ
- Jobs עיקריים:
  - `process_new_report(report_id)` - עיבוד דיווח חדש
  - `send_alerts_for_report()` - TODO: חתימה מלאה
  - `send_organization_alert()` - TODO: חתימה מלאה
  - `send_test_alert()` - TODO: חתימה מלאה
- תלות: database, services (google, nlp, email, telegram_alerts), i18n

### מודולים חסרים (מופיעים ב-imports)
- **app.api.v1.api** - API router aggregator
- **app.bot.webhook** - Telegram webhook router
- **app.bot.bot** - Telegram bot instance
- **app.admin.routes** - Admin interface routes
- **app.core.security** - Authentication/authorization
- **app.core.exceptions** - Custom exceptions
- **app.core.rate_limit** - Rate limiting logic
- **app.core.i18n** - Internationalization
- **app.services.email** - Email service
- **app.services.telegram_alerts** - Telegram alerts service
- **app.services.file_storage** - File storage service
- **app.services.geocoding** - Geocoding service
- **app.workers.manager** - Workers management

## מודל נתונים
טבלאות עיקריות (לפי databas.py):
- **users** - משתמשים עם roles
- **organizations** - ארגוני הצלה
- **reports** - דיווחים על בעלי חיים
- **alerts** - התראות לארגונים
- **events** - אירועי audit trail
- **report_files** - קבצים מצורפים לדיווחים

תמיכת GIS עם GeoAlchemy2 למיקומים גיאוגרפיים.

## נקודות API
### Reports API (prefix: /api/v1)
- `POST /api/v1/` - יצירת דיווח
- `GET /api/v1/{report_id}` - פרטי דיווח
- `PUT /api/v1/{report_id}` - עדכון דיווח
- `DELETE /api/v1/{report_id}` - מחיקת דיווח
- `GET /api/v1/` - רשימת דיווחים עם פילטרים
- `POST /api/v1/{report_id}/files` - העלאת קובץ
- `POST /api/v1/{report_id}/status` - שינוי סטטוס
- `GET /api/v1/stats/summary` - סטטיסטיקות

### System Endpoints
- `GET /health` - בדיקת תקינות
- `GET /metrics` - Prometheus metrics
- `GET /version` - מידע על הגרסה
- `GET /` - API root

### Telegram Webhook
- `/telegram/webhook` - TODO: endpoints מדויקים

### Admin Interface
- `/admin/*` - TODO: endpoints מדויקים

## Jobs/Workers ותורים
- **RQ Workers** על Redis DB 1
- משימות עיקריות:
  - עיבוד דיווחים חדשים (geocoding, NLP, organizations matching)
  - שליחת התראות לארגונים
  - TODO: משימות נוספות
- Timeout: 300 שניות (מ-config)
- Retries: עד 3 פעמים

## קונפיגורציה ו-ENV
משתני סביבה עיקריים (מ-config.py):
- **ENVIRONMENT** - development/testing/staging/production
- **SECRET_KEY** - מפתח הצפנה
- **DATABASE_URL** / **POSTGRES_*** - חיבור PostgreSQL
- **REDIS_HOST/PORT/PASSWORD** - חיבור Redis
- **TELEGRAM_BOT_TOKEN** - טוקן בוט
- **WEBHOOK_HOST/PATH** - Webhook configuration
- **GOOGLE_PLACES_API_KEY** - Google APIs
- **STORAGE_BACKEND** - local/s3/r2
- **S3_*** - הגדרות S3/R2 אם בשימוש
- **SMTP_*** - הגדרות דואר אלקטרוני
- **SENTRY_DSN** - Error tracking

## פריסה והרצה
### הרצה לוקאלית
```bash
# Development
python -m app.main
# או
uvicorn app.main:app --reload

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000
# או עם gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### Health Checks
- `/health` - בודק database, Redis, Google APIs, Telegram bot
- מחזיר סטטוסים: healthy/degraded/unhealthy

## תצפית וניטור
- **Logging**: structlog עם JSON/pretty format
- **Metrics**: Prometheus metrics ב-`/metrics`
  - http_requests_total
  - http_request_duration_seconds
  - telegram_messages_total
  - reports_created_total
  - alerts_sent_total
  - database_queries_total
- **Error Tracking**: Sentry (אם מוגדר SENTRY_DSN)
- **Request Tracing**: X-Request-ID headers

## i18n ואבטחה
### שפות
- תמיכה ב: עברית (he), ערבית (ar), אנגלית (en)
- ברירת מחדל: עברית

### אבטחה
- JWT authentication (python-jose)
- Password hashing (passlib/bcrypt)
- Rate limiting per user/IP
- CORS configuration
- Session management
- TODO: פירוט מנגנוני הרשאות

## מגבלות ידועות ו-TODO
### קבצים חסרים (מופיעים ב-imports אך לא קיימים)
- app/api/v1/api.py - Router aggregator
- app/bot/webhook.py - Webhook handler
- app/bot/bot.py - Bot instance
- app/admin/routes.py - Admin routes
- app/core/security.py - Auth logic
- app/core/exceptions.py - Custom exceptions
- app/core/rate_limit.py - Rate limiting
- app/core/i18n.py - Translations
- app/services/email.py - Email service
- app/services/telegram_alerts.py - Alerts service
- app/services/file_storage.py - Storage service
- app/services/geocoding.py - Geocoding service
- app/workers/manager.py - Workers manager

### TODO להמשך
- השלמת המודולים החסרים
- הגדרת Dockerfile לפריסה
- הוספת docker-compose.yml
- כתיבת tests
- תיעוד API מלא (OpenAPI)
- הגדרת CI/CD
- סקריפטי migration לבסיס נתונים

## הערות
- הקוד מכיל הרבה תיעוד באנגלית ועברית
- יש תמיכה מובנית ב-RTL ושפות מרובות
- המערכת בנויה לסקיילביליות עם async/await
- יש תמיכה ב-idempotency ו-retry logic