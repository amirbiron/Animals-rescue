## ARCHITECTURE

### תקציר

* מה המערכת עושה: שירות FastAPI עם בוט טלגרם לניהול דיווחי הצלת בעלי חיים. כולל יצירה וניהול דיווחים, עיבוד NLP בסיסי, גיאוקידינג/Places של Google, שליחת התראות לארגונים, אחסון קבצים, עבודות רקע באמצעות Redis/RQ, ומדדי Prometheus.
* רכיבי ליבה בפועל:
  * API (FastAPI): `app/main.py`, ראוטרים תחת `app/api/v1`, וראוטר Webhook לטלגרם ב-`app/bot/webhook.py`.
  * Bot (Telegram): `app/bot/handlers.py` מגדיר `bot_application`, `initialize_bot` ואת כל ה-handlers; Webhook ב-`app/bot/webhook.py`.
  * DB (PostgreSQL + SQLAlchemy 2 async): מודלים וקונפיג ב-`app/models/databas.py` (שימו לב לשם הקובץ).
  * Cache/Rate limit/Locks (Redis): `app/core/cache.py`.
  * Workers (RQ/Redis): עבודות ותזמונים ב-`app/workers/jobs.py`.
  * NLP: `app/services/nlp.py`.
  * Geocoding/Places: `app/services/google.py`.
  * File Storage: `app/services/file_storage.py`.
  * Security/Auth: `app/core/security.py`.
  * Config: `app/core/config.py`.

### סטאק ותלויות

* גרסת Python: 3.12+ (כפי שמוחזר מ-`/version` ב-`app/main.py`).
* ספריות עיקריות בקוד:
  * API: FastAPI, uvicorn
  * קונפיגורציה: pydantic v2, pydantic-settings
  * DB: SQLAlchemy 2.0 (async), asyncpg, GeoAlchemy2
  * Redis/Queue: redis.asyncio, rq, rq-scheduler
  * Bot: python-telegram-bot 22.x, httpx
  * אחסון קבצים: boto3, pillow, python-multipart
  * NLP: מודול פנימי (ללא מודל כבד בשימוש ישיר בקוד; יש הפניה ל-spaCy ב-`requirements.txt`)
  * לוגים ומדדים: structlog, prometheus-client
  * תבניות: jinja2
* שירותי צד-ג' בשימוש בקוד:
  * Telegram Bot API (Webhook ופעולות בוט)
  * Google Geocoding/Places (באמצעות `httpx` שירות מותאם)
  * S3/R2 (באמצעות boto3; מותנה קונפיג)
  * SMTP/דוא"ל: מוזכר (`app.services.email`) אך קובץ השירות לא קיים בריפו – TODO

### עץ תיקיות

```text
app/
  api/
    v1/
      api.py
      reports.py
  bot/
    handlers.py
    webhook.py
  core/
    cache.py
    config.py
    security.py
  main.py
  models/
    databas.py
  services/
    file_storage.py
    google.py
    nlp.py
  workers/
    jobs.py
README.md
requirements.txt
```

### מודולים וממשקים

* `app/main.py`: נקודת כניסה ל-FastAPI, קונפיגורציית middleware, handlers לחריגות, בריאות ומדדים, וכלילת ראוטרים.
  * פונקציות/אובייקטים:
    * `lifespan(app: FastAPI)`
    * `app = FastAPI(...)`
    * Middleware: `request_logging_middleware`, `rate_limiting_middleware`
    * Exception handlers: `animal_rescue_exception_handler`, `validation_exception_handler`, `not_found_handler`, `internal_server_error_handler`
    * Endpoints: `GET /health`, `GET /metrics`, `GET /version`, `GET /`, `GET /favicon.ico`, dev-only: `POST /dev/trigger-test-alert`, `GET /dev/db-stats`
    * `create_app() -> FastAPI`
  * תלויות עיקריות: `app.core.config.settings`, `app.models.database` (ראו הערת TODO לגבי שם הקובץ), `app.api.v1.api.api_router`, `app.bot.webhook.telegram_router`, `app.core.security.get_current_user`, ועוד.

* `app/api/v1/api.py`: Aggregator של ראוטרי API v1.
  * `api_router = APIRouter()`
  * כולל את `reports` תחת `/reports`
  * Endpoints נוספים: `GET /api/v1/health`, `GET /api/v1/info`

* `app/api/v1/reports.py`: נקודות קצה לניהול דיווחים (CRUD, קבצים, סטטוס, סטטיסטיקות) וסכמות Pydantic.
  * סכמות: `LocationModel`, `ReportCreateRequest`, `ReportUpdateRequest`, `ReportFileResponse`, `AlertResponse`, `ReportResponse`, `ReportListResponse`, `ReportSearchParams`
  * עזר: `get_report_by_id_or_public_id(...)`, `format_report_response(report)`
  * Endpoints:
    * `POST /api/v1/reports/` → `create_report(...)`
    * `GET /api/v1/reports/{report_id}` → `get_report(...)`
    * `PUT /api/v1/reports/{report_id}` → `update_report(...)`
    * `DELETE /api/v1/reports/{report_id}` → `delete_report(...)`
    * `GET /api/v1/reports/` → `list_reports(...)`
    * `POST /api/v1/reports/{report_id}/files` → `upload_report_file(...)`
    * `POST /api/v1/reports/{report_id}/status` → `update_report_status(...)`
    * `GET /api/v1/reports/stats/summary` → `get_reports_summary(...)`
  * תלויות: `app.core.config.settings`, `app.core.security`, `app.models.database` (ראו הערת TODO), `app.services.file_storage`, `app.services.geocoding` (ראו הערת TODO), `app.services.nlp`, `app.workers.jobs`.

* `app/bot/webhook.py`: REST Webhook עבור טלגרם.
  * ראוטר: `telegram_router = APIRouter()`
  * Endpoints: `POST /telegram/webhook`, `GET /telegram/webhook/info`, `POST /telegram/webhook/set`, `DELETE /telegram/webhook`, dev-only: `GET /telegram/webhook/test`, `POST /telegram/webhook/simulate`, `GET /telegram/health`
  * תלויות: `app.bot.handlers.bot_application`, `app.core.config.settings`

* `app/bot/handlers.py`: לוגיקת בוט טלגרם – שיחות, ניהול משתמשים, יצירת דיווח עם תמונות/מיקום/תיאור.
  * פונקציות עיקריות: `start_command`, `help_command`, `status_command`, `start_report_creation`, `handle_photo_upload`, `request_location`, `handle_location`, `request_description`, `handle_description`, `handle_report_confirmation`, `show_urgency_selection`, `show_animal_type_selection`, `handle_urgency_selection`, `handle_animal_type_selection`, `submit_report`, `cancel_conversation`, `handle_report_tracking`, `handle_report_sharing`, `error_handler`, `create_report_conversation_handler()`, `create_bot_application()`
  * אובייקטים: `bot_application`, `bot`, `initialize_bot()`
  * תלויות: `app.core.cache.redis_client`, `app.core.rate_limit` (ראו הערת TODO), `app.models.database`, `app.services.nlp`, `app.services.geocoding` (ראו הערת TODO), `app.services.file_storage`, `app.core.i18n` (ראו הערת TODO), `app.workers.jobs`

* `app/core/config.py`: קונפיגורציה עם Pydantic Settings.
  * מחלקה: `Settings(BaseSettings)` עם שדות רבים (APP, DB, Redis, Telegram, Google, Storage, Email, Logging, Sentry, i18n, Workers, Business Logic, Testing/Dev)
  * פונקציות: `get_settings()`, `setup_logging()`, עזר: `get_database_url()`, `is_feature_enabled()`
  * מאפיינים: `REDIS_URL`, `REDIS_QUEUE_URL`, `is_production`, `is_development`, `is_testing`, `DATABASE_ENGINE_OPTIONS`

* `app/core/cache.py`: Redis clients, Cache/Rate limiting/Locks/Sessions.
  * מחלקות: `RedisConfig`, `CacheManager`, `RateLimiter`, `DistributedLock`, `SessionManager`
  * פונקציות: `cached(...)` (דקורטור), `check_rate_limit(...)`, `redis_health_check()`, `close_redis_connections()`
  * אובייקטים גלובליים: `redis_client`, `redis_queue_client`, `redis_session_client`, `cache`, `rate_limiter`, `session_manager`

* `app/core/security.py`: אימות/הרשאות/JWT/סיסמאות/תלותים ל-FastAPI.
  * פונקציות: `create_password_hash`, `verify_password`, `create_access_token`, `create_telegram_auth_token`, `decode_token`, `get_current_user`, `require_authentication`, `require_roles`, `require_admin`, `require_org_staff`, `can_access_report`, `can_modify_report`, `can_manage_organization`, `get_security_headers`, `validate_request_source`

* `app/models/databas.py`: מודלים ו-Enums של המערכת, קונפיגורציית מנוע/סשן, Utilities ובריאות DB.
  * Enums: `UserRole`, `ReportStatus`, `AnimalType`, `UrgencyLevel`, `OrganizationType`, `AlertChannel`, `AlertStatus`, `FileType`, `EventType`
  * מודלים: `User`, `Organization`, `Report`, `ReportFile`, `Alert`, `Event`
  * Engine/Session: `engine`, `async_session_maker`, תלותים: `create_async_engine`
  * תלותים: `get_db_session()`, `create_tables()`, `drop_tables()`, `check_database_health()`
  * Utilities: `create_point_from_coordinates(...)`, `calculate_distance_km(...)`

* `app/services/file_storage.py`: אחסון קבצים (Local/S3-R2), ולידציה/מטאדטה/thumbnail.
  * מחלקות: `FileStorageBackend` (base), `LocalFileStorage`, `S3FileStorage`, `FileStorageService`
  * מתודות עיקריות: `upload_file(...)`, `download_file(...)`, `delete_file(...)`, `file_exists(...)`, `get_file_info(...)`

* `app/services/google.py`: אינטגרציית Google Places/Geocoding עם caching, rate limit, Circuit Breaker.
  * מחלקות: `GoogleService`, `GeocodingService`
  * מתודות מפתח: `search_places(...)`, `get_place_details(...)`, `search_veterinary_clinics(...)`, `geocode(...)`, `reverse_geocode(...)`, `test_connection(...)`, `get_service_status(...)`

* `app/services/nlp.py`: עיבוד שפה טבעית בסיסי.
  * מחלקות: `NLPService` (כוללת: `LanguageDetector`, `KeywordExtractor`, `UrgencyDetector`, `AnimalClassifier`, `SentimentAnalyzer`)
  * מתודות מפתח: `analyze_text(...)`, `analyze_report_content(...)`, `generate_title(...)`, `calculate_text_similarity(...)`, `get_service_stats(...)`

* `app/workers/jobs.py`: עבודות רקע RQ ותזמון.
  * תורים: "default", "alerts", "maintenance", "external"
  * עבודות: `process_new_report(report_id)`, `send_organization_alert(report_id, organization_id, channel)`, `retry_failed_alerts()`, `cleanup_old_data()`, `update_organization_stats()`, `sync_google_places_data()`, `send_test_alert(message)`, `generate_daily_statistics()`
  * תזמון: `schedule_recurring_jobs()` (rq-scheduler)

תלות בין מודולים (imports מרכזיים):
* `app/main.py` כולל: `api_router` (`app/api/v1/api.py`), `telegram_router` (`app/bot/webhook.py`), `settings`, `security`, `models` (ראו TODO לגבי `database`/`databas`).
* `app/api/v1/reports.py` תלוי ב-`core.security`, `core.config`, `models.database` (TODO), `services.file_storage`, `services.geocoding` (TODO), `services.nlp`, `workers.jobs`.
* `app/bot/*` תלוי ב-`core.cache`, `core.rate_limit` (TODO), `models.database`, `services.*`, `core.i18n` (TODO).
* `workers/jobs.py` תלוי ב-`services.google`, `services.nlp`, `services.email` (TODO), `services.telegram_alerts` (TODO), `core.i18n` (TODO), `models`.

### מודל נתונים

* ישויות עיקריות:
  * User: פרטי משתמש, תפקיד (`UserRole`), שדה `telegram_user_id`, סטטוס/אמון/סטטיסטיקות, שיוך לארגון אופציונלי.
  * Organization: מידע ארגון (וטרינרים/מקלטים/ממשלה/מתנדבים), כתובת/עיר, קואורדינטות (`Geometry(POINT)` ו/או `latitude/longitude`), רדיוס שירות, ערוצי התראות מועדפים, `telegram_chat_id`.
  * Report: דיווח על אירוע בעל חיים – כותרת/תיאור, סיווגי `AnimalType`, `UrgencyLevel`, סטטוס `ReportStatus`, מיקום/כתובת/עיר/דיוק, תוצאות NLP (keywords/sentiment), זיהוי כפולות, מזהה ציבורי `public_id`, זמני first_response/resolved, שיוך לארגון מטפל.
  * ReportFile: קבצים מצורפים לדיווח (PHOTO/VIDEO/AUDIO/DOCUMENT), מטאדטה, מיקום אחסון (local/s3/r2), אופציונלית ממדים/משך/thumbnail.
  * Alert: התראות לארגונים: ערוץ (`AlertChannel`), סטטוס (`AlertStatus`), מעקב משלוח/נסיונות/שגיאה/Retry.
  * Event: יומן אירועים (audit/outbox) עם `EventType`, payload וסטטוס עיבוד.
* קשרים:
  * `User` 1:N `Report`
  * `Organization` 1:N `User` (staff) ו-1:N `Alert`
  * `Report` 1:N `ReportFile` ו-1:N `Alert` ; `Report` -> `Organization` (Assigned, אופציונלי)
  * `Alert` -> (`Report`, `Organization`)
  * `Event` -> `User` (אופציונלי)

### נקודות API

* מהאפליקציה הראשית (`app/main.py`):
  * `GET /` — מידע כללי
  * `GET /health` — בדיקת בריאות כוללת
  * `GET /metrics` — מדדי Prometheus
  * `GET /version` — פרטי גרסה
  * dev-only: `POST /dev/trigger-test-alert`, `GET /dev/db-stats`
* API v1 (`app/api/v1/api.py`):
  * `GET /api/v1/health` — בריאות API v1
  * `GET /api/v1/info` — מידע API v1
  * Reports (`app/api/v1/reports.py`, עם prefix `/api/v1/reports`):
    * `POST /api/v1/reports/` — יצירת דיווח
    * `GET /api/v1/reports/{report_id}` — שליפת דיווח (ID או `public_id`)
    * `PUT /api/v1/reports/{report_id}` — עדכון דיווח
    * `DELETE /api/v1/reports/{report_id}` — מחיקת דיווח (admin)
    * `GET /api/v1/reports/` — חיפוש/רשימה עם סינון/מיון/עמוד
    * `POST /api/v1/reports/{report_id}/files` — העלאת קובץ לדיווח
    * `POST /api/v1/reports/{report_id}/status` — עדכון סטטוס (צוות ארגון)
    * `GET /api/v1/reports/stats/summary` — סטטיסטיקות סיכום
* Telegram Webhook (`app/bot/webhook.py`, עם prefix `/telegram`):
  * `POST /telegram/webhook` — קבלת עדכוני טלגרם
  * `GET /telegram/webhook/info` — מידע Webhook
  * `POST /telegram/webhook/set` — הגדרת Webhook
  * `DELETE /telegram/webhook` — מחיקת Webhook
  * dev-only: `GET /telegram/webhook/test`, `POST /telegram/webhook/simulate`
  * `GET /telegram/health` — בריאות רכיב הבוט

### Jobs/Workers ותורים

* תורים: `default`, `alerts`, `maintenance`, `external` (ע"פ דקורטור `@job`)
* עבודות מרכזיות:
  * `process_new_report(report_id)` [default]: עיבוד דיווח חדש (העשרה, חיפוש ארגונים, NLP, אירועי audit, תור התראות)
  * `send_organization_alert(report_id, organization_id, channel)` [alerts]: שליחת התראה בערוץ רלוונטי
  * `retry_failed_alerts()` [alerts]: תזמון נסיונות חוזרים
  * `cleanup_old_data()` [maintenance]: ניקוי נתונים ישנים
  * `update_organization_stats()` [maintenance]: עדכון סטטיסטיקות ארגונים
  * `sync_google_places_data()` [external]: סנכרון נתוני Places לארגונים
  * `send_test_alert(message)` [default]: בדיקת התראה
  * `generate_daily_statistics()` [maintenance]: הפקת סטטיסטיקות יומיות ושמירתן ב-Redis
  * `schedule_recurring_jobs()` – תזמון קרוני עם rq-scheduler

### קונפיגורציה ו-ENV

* קובץ ENV: מוגדר `env_file=".env"` עם קידוד UTF-8.
* קבוצות משתנים עיקריות (מחלקת `Settings`):
  * אפליקציה: `APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION`, `ENVIRONMENT` (development/testing/staging/production), `DEBUG`, `API_V1_PREFIX`, `CORS_ORIGINS`, `SHOW_DOCS`, `AUTO_RELOAD`
  * DB: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (נבנה `DATABASE_URL` עם `postgresql+asyncpg`)
  * Redis: `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`, `REDIS_MAX_CONNECTIONS` (+ מאפייני `REDIS_URL`, `REDIS_QUEUE_URL`)
  * Telegram: `TELEGRAM_BOT_TOKEN` (נדרש), `TELEGRAM_WEBHOOK_SECRET` (אופציונלי), `WEBHOOK_HOST`, `WEBHOOK_PATH`
  * Google: `GOOGLE_PLACES_API_KEY`, `GOOGLE_GEOCODING_API_KEY`, `GOOGLE_API_RATE_LIMIT`, `GOOGLE_API_QUOTA_DAILY`
  * Storage: `STORAGE_BACKEND` (local/s3/r2), `UPLOAD_DIR`, `MAX_FILE_SIZE_MB`, `ALLOWED_FILE_TYPES`, ובמצב s3/r2: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `S3_REGION`
  * Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS`, `EMAILS_FROM_EMAIL`, `EMAILS_FROM_NAME`
  * Logging/Monitoring: `LOG_LEVEL`, `LOG_FORMAT` (json/pretty), `SENTRY_DSN`, `METRICS_ENABLED`, `HEALTH_CHECK_PATH`
  * i18n: `SUPPORTED_LANGUAGES` (ברירת מחדל: he, ar, en), `DEFAULT_LANGUAGE`
  * Workers: `WORKER_PROCESSES`, `WORKER_TIMEOUT`, `JOB_MAX_RETRIES`, `JOB_RETRY_DELAY`
  * Business Logic: `REPORT_EXPIRY_DAYS`, `MAX_REPORTS_PER_USER_PER_DAY`, `SEARCH_RADIUS_KM`, `MAX_SEARCH_RADIUS_KM`, `ALERT_TIMEOUT_MINUTES`, `MAX_ALERTS_PER_REPORT`, `ENABLE_TRUST_SYSTEM`, `MIN_TRUST_SCORE`, `MAX_TRUST_SCORE`
  * Testing/Dev: `TESTING`, `TEST_DATABASE_URL`, ועוד.

### פריסה והרצה

* הרצה לוקאלית:
  * API: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
  * Production (מצוין בתיעוד קוד): `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker`
* Workers (RQ): יש עבודות RQ המוגדרות ב-`app/workers/jobs.py`. נדרש תהליך worker נפרד וחיבור ל-Redis. TODO: אין `app/workers/manager.py` למרות שמיובא ב-`main.py`; יש להשלים מנגנון הפעלה/תצורה ל-workers.
* פריסה: לא נמצאו קבצי Docker/Compose/Render/Fly/Procfile. TODO: להוסיף קונפיג קונטיינר/CI/CD.
* Health checks: `GET /health`, `GET /api/v1/health`, `GET /telegram/health`.

### תצפית וניטור

* לוגים: `structlog` עם תצורה דרך `setup_logging()`.
* מדדים: `prometheus_client` עם Counters/Histogram ו-`GET /metrics`.
* Sentry: `SENTRY_DSN` קיים בקונפיג אך אינטגרציה/אתחול SDK לא מופיע בקוד. TODO.
* Tracing: ספריות OpenTelemetry מופיעות ב-`requirements.txt` אך לא בשימוש בקוד. TODO.

### i18n ואבטחה

* i18n:
  * שפות נתמכות: `he`, `ar`, `en` (מהקונפיג).
  * בקוד יש שימושים ב-`app.core.i18n.get_text/detect_language/set_user_language` (בבוט ובעבודות), אך מודול זה לא קיים בריפו. TODO.
* אבטחה:
  * JWT (אלגוריתם HS256), אימות דרך HTTP Bearer (`get_current_user`/`require_authentication`), תפקידי RBAC דרך `require_roles`.
  * Hash סיסמאות באמצעות `passlib[bcrypt]`.
  * כותרות אבטחה (`get_security_headers`).
  * CORS/TrustedHost/Sessions מוגדרים ב-`main.py` לפי סביבה.
  * Rate limiting: Middleware ב-`main.py` משתמש ב-`app.core.rate_limit` (לא קיים); קיימת מימוש אלגוריתמים ב-`app/core/cache.py` (`check_rate_limit`, `RateLimiter`). TODO לתאם ייבוא/מבנה.

### מגבלות ידועות ו-TODO

* אי-התאמות שמות/ייבוא:
  * `app/models/databas.py` קיים, אך הקוד מייבא `app.models.database`. TODO: ליישר שם קובץ/ייבוא.
  * `app.bot.bot` מיובא ב-`main.py` לצורך `bot`/`initialize_bot`, אך בפועל הפונקציות נמצאות ב-`app/bot/handlers.py`. TODO: לתקן נתיב הייבוא או לפצל קובץ.
  * `app.workers.manager` מיובא ב-`main.py` אך אינו קיים. TODO.
  * `app.admin.routes` מיובא ב-`main.py` אך אין תיקיה/קובץ `app/admin/routes.py`. TODO.
  * `app.core.exceptions` מיובא במספר מקומות, אך קובץ זה לא קיים. TODO.
  * `app.core.rate_limit` מיובא במספר מקומות, אך לא קיים; פונקציות קיימות תחת `app.core.cache`. TODO.
  * `app.core.i18n` (get_text/detect_language/set_user_language) בשימוש – המודול לא קיים. TODO.
  * `app.services.geocoding` מיובא אך `GeocodingService` מוגדר ב-`app/services/google.py`. TODO.
  * `app.services.email` ו-`app.services.telegram_alerts` מיובאים ב-`workers/jobs.py` – לא קיימים. TODO.
  * נתיבי תבניות: `app/templates/alerts` בשימוש (Jinja2) – לא קיים בריפו. TODO.
  * בבוט: `from app.workers.jobs import ... send_alerts_for_report` מיובא אך לא קיים בפועל; יש `send_organization_alert`. TODO.
* RQ ו-Redis:
  * בקוד נעשה שימוש ב-`redis.asyncio` גם עבור scheduler של RQ; RQ מצפה לקליינט סינכרוני סטנדרטי. נדרש אימות/התאמה. TODO.
* JWT ספרייה:
  * הקוד משתמש ב-`import jwt` (PyJWT), אך ב-`requirements.txt` יש `python-jose` ולא PyJWT. יש ליישר תלות/מימוש. TODO.
* באגים/חוסר עקביות ידועים:
  * `can_modify_report` ב-`security.py` משווה `report.status` למחרוזות ("resolved"/"closed") במקום Enum `ReportStatus`. TODO.
  * GIS: שימוש ב-`Geometry(POINT)` דורש PostGIS במסד. ודאו שהסכמה תואמת. TODO.
* פריסה:
  * חסרים קבצי Docker/Compose/CI/CD. TODO.

המסמך לעיל נסמך אך ורק על הקבצים הקיימים בריפו במועד כתיבתו. בכל מקום בו חסר מידע/קובץ – סומן TODO במפורש.

