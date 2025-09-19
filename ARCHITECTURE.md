# ARCHITECTURE

## תקציר
- המערכת: FastAPI API עם נקודות בריאות/מדדים/מידע גרסה, בוט טלגרם לניהול שיחות דיווח, Workers (RQ) לעיבוד רקע, PostgreSQL (SQLAlchemy Async), Redis לקאש/Rate limit/תורים, שירותי NLP ואינטגרציות Google.
- רכיבי ליבה בפועל:
  - `app/main.py`: אתחול FastAPI, מידלוורים, מדדים, נקודות בריאות וגרסה, הכללת ראוטרים (חלקם חסרים בפועל – ראו TODO).
  - `app/api/v1/reports.py`: ראוטר לניהול דיווחים (CRUD, קבצים, סטטיסטיקות). כרגע לא משויך ישירות ל-`app` בקוד הקיים (ראו TODO Mount).
  - `app/bot/handlers.py`: בוט טלגרם וזרימות שיחה לדיווח, יצירת `bot_application` ו-`bot`.
  - `app/models/databas.py`: כל מודלי ה-ORM, יצירת מנוע, סשן, ו-DB utils (כולל Health check).
  - `app/core/cache.py`: Redis clients, Cache, Rate limiter, Distributed locks, Sessions.
  - `app/core/config.py`: `Settings` (Pydantic v2) וניהול קונפיג/לוגים.
  - `app/services/google.py`: אינטגרציית Google (Geocoding/Places) + Cache + Circuit breaker.
  - `app/services/nlp.py`: שירות NLP פנימי (זיהוי שפה/דחיפות/סוג חיה/רגש/דמיון).
  - `app/workers/jobs.py`: משימות רקע (RQ) – עיבוד דיווחים, שליחת התראות, ניקוי, סטטיסטיקות, סינכרון Google.

## סטאק ותלויות
- Python: 3.12+ (עפ"י `app/main.py:/version`).
- Web/API: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`.
- DB/ORM: `sqlalchemy[asyncio]`, `asyncpg`, `alembic` (מיגרציות; לא נראה בקוד העדכני), שימוש ב-`Geometry` (GeoAlchemy2) במודלים – TODO: לא מופיע ב-`requirements.txt`.
- Redis/Queues: `redis[hiredis]`, `rq`, `rq-scheduler`.
- Bot: `python-telegram-bot[webhooks]`.
- HTTP/Clients: `httpx`.
- NLP: `spacy` + מודל `he-core-news-sm` מופיעים ב-`requirements.txt` אך בקוד בפועל נעשה שימוש ב-NLP פנימי – TODO אימות/ניקוי.
- אחסון/קבצים: `pillow`, `python-multipart`, `boto3` (S3/R2; השירות בפועל `FileStorageService` לא קיים בקוד – TODO).
- אבטחה: `python-jose[cryptography]`, `passlib`; בקוד קיימות קריאות ל-`app.core.security` אך המודול לא קיים – TODO.
- ניטור/מדדים/לוגים: `structlog`, `prometheus-client`; `sentry-sdk`, `opentelemetry-*` ב-`requirements.txt` אך לא מחוברים בקוד – TODO.

## עץ תיקיות (סיכום)
- app/
  - api/
    - v1/
      - reports.py
  - bot/
    - handlers.py
  - core/
    - cache.py
    - config.py
  - main.py
  - models/
    - databas.py
  - services/
    - google.py
    - nlp.py
  - workers/
    - jobs.py
- README.md
- requirements.txt

## מודולים וממשקים
- `app/main.py`
  - תפקיד: אתחול האפליקציה, מידלוורים (CORS, GZip, TrustedHost, Session), מדדי Prometheus, Handlers לחריגות, Health/metrics/version/root, Mount סטטי בזמן פיתוח, הכללת ראוטרים.
  - נק"נ קיימות: `GET /health`, `GET /metrics`, `GET /version`, `GET /`, `GET /favicon.ico`. בזמן פיתוח: `POST /dev/trigger-test-alert`, `GET /dev/db-stats`.
  - פונקציות: `create_app() -> FastAPI`.
  - תלות: `app.core.config.settings/setup_logging`, `app.models.database.*`, `app.core.cache.redis_client`, Prometheus `Counter/Histogram`.
  - החלטות: מדדים מובְנים (בקשות, משך, דיווחים, התראות, שאילתות DB), Rate limit במידלוור (ראו הערת TODO לנתיב המודול), Health משולב.

- `app/api/v1/reports.py` (APIRouter – לא משוייך כרגע ל-app)
  - תפקיד: API לדיווחים (יצירה/קריאה/עדכון/מחיקה, חיפוש/סינון, קבצים, סטטיסטיקות, עדכון סטטוס).
  - נק"נ יחסיות בתוך ה-router:
    - `POST /` create_report
    - `GET /{report_id}` get_report
    - `PUT /{report_id}` update_report
    - `DELETE /{report_id}` delete_report (204)
    - `GET /` list_reports (חיפוש/פאג’ינציה)
    - `POST /{report_id}/files` upload_report_file
    - `POST /{report_id}/status` update_report_status
    - `GET /stats/summary` get_reports_summary
  - תלות: `app.models.database` (ORM), `app.services.nlp`, `app.services.google` (GeocodingService), `FileStorageService` (חסר), Rate limit ואבטחה (מודולים חסרים – ראו TODO).

- `app/bot/handlers.py`
  - תפקיד: בוט טלגרם מלא לזרימת דיווחים (תמונות→מיקום→תיאור→אישור), פקודות `/start`, `/help`, `/status`, יצירת `bot_application` ו-`bot`, `initialize_bot()` (Webhook בבוט עצמו; אין ראוטר HTTP לקליטת webhook).
  - נק"נ/מחלקות: `create_bot_application() -> Application`, `initialize_bot()`, `bot_application`, `bot`, Handlers רבים לשיחות (ConversationHandler).
  - תלות: `app.models.database`, `app.services.nlp`, `app.services.google`, `app.core.cache`, `rq` jobs מ-`app.workers.jobs`.

- `app/models/databas.py`
  - תפקיד: מודלי ORM מלאים: `User`, `Organization`, `Report`, `ReportFile`, `Alert`, `Event` + `Enums` (Role/Status/Type/Channel/…); מנוע/סשן; יצירת טבלאות; Health DB.
  - נק"נ: `engine`, `async_session_maker`, `get_db_session()`, `create_tables()`, `drop_tables()`, `check_database_health()`.
  - תלות: PostgreSQL, שימוש ב-`Geometry("POINT")` (GeoAlchemy2) – TODO תלות חסרה ב-`requirements.txt`.

- `app/core/cache.py`
  - תפקיד: Redis (clients), Cache (`CacheManager`), Rate limiting (`RateLimiter` + `check_rate_limit()`), Distributed lock (`DistributedLock`/`distributed_lock`), ניהול סשנים.
  - אובייקטים ציבוריים: `redis_client`, `redis_queue_client`, `redis_session_client`, `cache`, `rate_limiter`, `session_manager`.

- `app/core/config.py`
  - תפקיד: קונפיג Pydantic Settings, חישוב `DATABASE_URL`, קבצי ENV, `setup_logging()`.
  - אובייקטים/פונקציות: `Settings`, `get_settings()`, `settings`, `setup_logging()`, `get_database_url()`.

- `app/services/google.py`
  - תפקיד: `GoogleService` (Places/Geocoding עם Rate limit/Cache/Circuit breaker) ו-`GeocodingService` עטיפה פשוטה.

- `app/services/nlp.py`
  - תפקיד: `NLPService` עם `analyze_text()`, `analyze_report_content()`, `generate_title()`, `calculate_text_similarity()`. מחלקות עזר (Detector/Classifier/Sentiment וכו’).

- `app/workers/jobs.py`
  - תפקיד: משימות RQ:
    - `process_new_report` (queue: `default`)
    - `send_organization_alert` (queue: `alerts`)
    - `retry_failed_alerts` (queue: `alerts`)
    - `cleanup_old_data` (queue: `maintenance`)
    - `update_organization_stats` (queue: `maintenance`)
    - `sync_google_places_data` (queue: `external`)
    - `send_test_alert` (queue: `default`)
    - `generate_daily_statistics` (queue: `maintenance`)
    - `schedule_recurring_jobs()` לקביעת Cron דרך `rq-scheduler`.

## מודל נתונים
- `User` (טבלה: `users`): שדות עיקריים – `telegram_user_id`, `role`, `language`, `timezone`, סטטוסים (`is_active`, `is_verified`), מדדים (`reports_count`, `successful_reports_count`), קשר ל-`Organization` ול-`Report`. אינדקסים על מזהים/תפקיד/ארגון/אמון.
- `Organization` (טבלה: `organizations`): `organization_type`, `specialties[]`, פרטי קשר (`primary_phone`, `email`, `website`), כתובת/עיר, `location` (Geometry POINT) וגם `latitude/longitude`, `service_radius_km`, `is_24_7`, סטטיסטיקות תגובה, ערוצי התראות (`alert_channels[]`, `telegram_chat_id`). אינדקסים על מיקום/עיר/סוג/סטטוס.
- `Report` (טבלה: `reports`): `reporter_id`, `title/description`, `animal_type`, `urgency_level`, `status`, מיקום (`location`/`latitude`/`longitude`/`city`), אימות כתובת, `language`, `keywords[]`, `sentiment_score`, דופליקציה (`is_duplicate`, `duplicate_of_id`), `public_id`, זמנים (`first_response_at`, `resolved_at`), שיוך לארגון. אינדקסים על סטטוס/חיה/דחיפות/עיר/יצירה/מיקום.
- `ReportFile` (טבלה: `report_files`): קישור לדיווח, `file_type`, `mime_type`, `file_size_bytes`, `storage_backend`, `storage_path/url`, `width/height/duration`, `file_hash`. אינדקסים לפי דיווח/סוג/Hash/Backend.
- `Alert` (טבלה: `alerts`): `report_id`, `organization_id`, `channel`, `recipient`, `subject/message/template`, `status`, תזמונים/נסיונות/Retry, `external_id`, תגובה. אינדקסים לפי דיווח/ארגון/סטטוס/ערוץ/זמנים, ייחודיות (`report_id`,`organization_id`,`channel`).
- `Event` (טבלה: `events`): `event_type`, `entity_type/id`, `payload`, `user_id`, `processed/processed_at` – מסייע ל-Outbox/Audit trail. אינדקסים לפי סוג/ישות/משתמש/סטטוס/יצירה.

## נקודות API
- FastAPI (מוגדר בפועל ב-`app/main.py`):
  - `GET /health`: בדיקות DB/Redis/Google/Telegram; מחזיר 200/503 בהתאם.
  - `GET /metrics`: מדדי Prometheus בפורמט טקסט.
  - `GET /version`: מידע גרסה/סביבה.
  - `GET /`: דף שורש עם מטא-מידע בסיסי.
  - פיתוח בלבד: `POST /dev/trigger-test-alert`, `GET /dev/db-stats`.
- Reports API (ב-`app/api/v1/reports.py`): מוגדר כ-APIRouter אך אינו משוייך כרגע ל-`app` – TODO Mount. נתיבים יחסיים בראוטר: `POST /`, `GET /{report_id}`, `PUT /{report_id}`, `DELETE /{report_id}`, `GET /`, `POST /{report_id}/files`, `POST /{report_id}/status`, `GET /stats/summary`.
- Webhookים: לוגיקת Webhook של טלגרם קיימת בהגדרת הבוט (`initialize_bot()` קורא `bot.set_webhook`), אך אין ראוטר HTTP בפועל (`app.bot.webhook` חסר) – TODO הוספת Endpoint HTTP לדחיפת Telegram.

## Jobs/Workers ותורים
- תורים (RQ): `default`, `alerts`, `maintenance`, `external`.
- יצרנים: API והבוט מדביקים משימות כמו `process_new_report.delay(...)` ושליחת התראות. הערה: בבוט נעשה שימוש ב-`send_alerts_for_report.delay` שאינו קיים – TODO תיקון לשימוש ב-`send_organization_alert`/תזמור מתאים.
- צרכנים: פונקציות מסומנות ב-`@job` ב-`app/workers/jobs.py`. משימות מחזוריות דרך `rq-scheduler` (`schedule_recurring_jobs`).

## קונפיגורציה ו-ENV
- מקור: `app/core/config.py` (Pydantic Settings; `env_file` ברירת מחדל `.env`). משתנים עיקריים:
  - אפליקציה: `APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION`, `ENVIRONMENT`, `DEBUG`, `API_V1_PREFIX`, `CORS_ORIGINS`, `SHOW_DOCS`, `AUTO_RELOAD`.
  - DB (Postgres): `POSTGRES_HOST/PORT/DB/USER/PASSWORD`, נגזר: `DATABASE_URL`, `DATABASE_*` (Pool/Echo).
  - Redis: `REDIS_HOST/PORT/DB/PASSWORD`, URLs ל-Queue/Session, `REDIS_MAX_CONNECTIONS`.
  - Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `WEBHOOK_HOST`, `WEBHOOK_PATH` (נגזר `TELEGRAM_WEBHOOK_URL`), Rate limit לבוט.
  - Google: `GOOGLE_PLACES_API_KEY`, `GOOGLE_GEOCODING_API_KEY`, `GOOGLE_API_RATE_LIMIT`, `GOOGLE_API_QUOTA_DAILY`.
  - אחסון קבצים: `STORAGE_BACKEND` (`local`/`s3`/`r2`), `UPLOAD_DIR`, `MAX_FILE_SIZE_MB`, `ALLOWED_FILE_TYPES`, `S3_*` (נדרשים כשלא local).
  - דוא"ל: `SMTP_HOST/PORT/USER/PASSWORD`, `EMAILS_FROM_EMAIL/NAME`.
  - לוגים/ניטור: `LOG_LEVEL`, `LOG_FORMAT` (`json`/`pretty`), `SENTRY_DSN`, `METRICS_ENABLED`, `HEALTH_CHECK_PATH`.
  - i18n: `SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`.
  - Workers: `WORKER_PROCESSES`, `WORKER_TIMEOUT`, `JOB_MAX_RETRIES`, `JOB_RETRY_DELAY`.
  - ביזנס: `REPORT_EXPIRY_DAYS`, `MAX_REPORTS_PER_USER_PER_DAY`, `SEARCH_RADIUS_KM`, `MAX_SEARCH_RADIUS_KM`, `ALERT_TIMEOUT_MINUTES`, `MAX_ALERTS_PER_REPORT`, `ENABLE_TRUST_SYSTEM`, `MIN_TRUST_SCORE`.

## פריסה והרצה
- הרצה לוקאלית (מתוך `app/main.py`):
  - `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` (עפ"י `settings.AUTO_RELOAD`).
  - פרודקשן: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker`.
- קבצי פריסה: לא נמצאו `Dockerfile`/`docker-compose`/CI – TODO הוספה במידת הצורך.
- Health checks: `GET /health` (200/503), `GET /metrics`.

## תצפית וניטור
- לוגים: `structlog` עם `setup_logging()`; רמות לוגר של uvicorn/httpx מונמכות בפרודקשן.
- מדדים (Prometheus): Counters/Histogram: `http_requests_total`, `http_request_duration_seconds`, `telegram_messages_total`, `reports_created_total`, `alerts_sent_total`, `database_queries_total`.
- Sentry/OpenTelemetry: קיימים ב-`requirements`/`settings` אך לא מחוברים – TODO אינטגרציה.

## i18n ואבטחה
- i18n: בקוד הבוט שימוש ב-`app.core.i18n` (`get_text/detect_language/set_user_language`) – המודול אינו קיים בריפו – TODO.
- אבטחה/אימות: בקבצי API יש שימוש ב-`get_current_user`, `require_roles` מ-`app.core.security` – המודול חסר – TODO. JWT/סיסמאות קיימים כתלויות בלבד.
- Rate limit: קיים בפועל דרך Redis (`app/core/cache.py`) ומשמש בבוט וב-API (במידלוור) – הערת נתיב יבוא: חלק מהקוד מייבא `app.core.rate_limit` שאינו קיים – TODO לתקן ליבוא מ-`app.core.cache` או ליצור מודול דק.

## מגבלות ידועות ו-TODO
- Mount של ה-API v1: `app/main.py` מנסה `from app.api.v1.api import api_router` – קובץ חסר. הראוטר ב-`app/api/v1/reports.py` לא משוייך לאפליקציה – TODO ליצור/לשייך.
- Webhook טלגרם: `from app.bot.webhook import telegram_router` חסר – TODO להוסיף Endpoint HTTP או להתאים את הבוט.
- אבטחה: `app.core.security` חסר – TODO מימוש `get_current_user`/`require_roles`/JWT.
- Rate limit: תיקון יבוא ל-`check_rate_limit/RateLimitExceeded` (נמצאים ב-`app.core.cache`).
- שירותי צד: `FileStorageService`, `EmailService`, `TelegramAlertsService` חסרים – TODO מימוש/החלפה.
- תבניות: נתיב `app/templates/alerts` לא קיים – TODO להוסיף תבניות Jinja2.
- DB מודול: שם קובץ הוא `databas.py` אך היבוא בקוד רבים הוא `app.models.database` – TODO יישור שם קובץ/יבוא.
- GeoAlchemy2: שימוש ב-`Geometry` במודלים אך לא ב-`requirements.txt` – TODO הוספה.
- NLP/Spacy: תלויות Spacy/מודל עברית ב-`requirements.txt` אך לא בשימוש בקוד – TODO אימות/ניקוי.
- Admin: `app.admin.routes` חסר – TODO או להסיר הכללה.
- Workers Manager: `app.workers.manager` חסר – TODO הפעלה/ניהול Workers.

## אימות עצמי לפני מסירה
- [x] לא הומצאו נתיבים/מחלקות (ציינו רק מה שקיים או סומן TODO).
- [x] כל שם שמופיע במסמך קיים בקוד או ב-`requirements`/`settings`.
- [x] אין קוד חדש במסמך (תיעוד בלבד).
- [x] יש TODO בכל מקום שהיה חסר/סתירה.

