---
# Portfolio – בוט חילוץ בעלי חיים

name: "בוט חילוץ בעלי חיים"
repo: "https://github.com/amirbiron/Animals-rescue"
status: "פעיל"

one_liner: "מערכת אוטומטית לדיווח ושיגור חילוץ בעלי חיים דרך טלגרם, עם התאמה גיאוגרפית לארגונים ולוח בקרה למנהלים"

stack:
  - Python 3.12+
  - FastAPI (async)
  - SQLAlchemy 2.0 (async) + Alembic
  - PostgreSQL + PostGIS
  - Redis + RQ Workers
  - python-telegram-bot 22.4+
  - Google Places / Geocoding APIs
  - SerpAPI
  - spaCy (NLP)
  - Prometheus
  - Sentry
  - Twilio (SMS/WhatsApp)
  - AWS S3/R2 (אחסון קבצים)
  - Docker

key_features:
  - ממשק טלגרם לדיווח עם תמונות, מיקום ותיאור
  - תמיכה בריבוי שפות – עברית, ערבית, אנגלית (זיהוי אוטומטי)
  - התאמה גיאוגרפית אוטומטית של דיווחים לארגוני חילוץ
  - התראות מייל וטלגרם לעמותות/מקלטים/מתנדבים/רשויות
  - עיבוד שפה טבעית (NLP) לזיהוי דחיפות וסיווג
  - לוח בקרה למנהלים עם ניהול משתמשים, ארגונים ודיווחים
  - עיבוד רקע אסינכרוני עם Redis/RQ
  - אנליטיקה וניטור בזמן אמת (Prometheus)
  - SMS/WhatsApp alerts דרך Twilio

architecture:
  summary: |
    מערכת מיקרו-שירותים עם FastAPI כשרת ראשי:
    - API layer (REST) – דיווחים, ניהול ארגונים, אדמין
    - Telegram Bot – ממשק משתמש עם handlers ו-webhook
    - Workers (RQ) – עיבוד רקע (NLP, geocoding, alerts)
    - PostgreSQL+PostGIS – מסד נתונים עם תמיכה גיאוגרפית
    - Redis – קאשינג, סשנים, תורי משימות
  entry_points:
    - app/main.py – נקודת כניסה ראשית (FastAPI + Telegram webhook)
    - app/bot/handlers.py – טיפול בהודעות טלגרם
    - app/workers/jobs.py – משימות רקע
    - admin/routes.py – לוח בקרה למנהלים

demo:
  live_url: "" # TODO: בדוק ידנית
  video_url: "" # TODO: בדוק ידנית

setup:
  quickstart: |
    1. git clone <repo-url> && cd Animals-rescue
    2. cp .env.example .env && # מלא API keys
    3. docker-compose up --build
    4. docker-compose exec api alembic upgrade head

your_role: "פיתוח מלא – ארכיטקטורה, backend, אינטגרציות חיצוניות, NLP, deployment"

tradeoffs:
  - מערכת מורכבת עם הרבה תלויות חיצוניות (Google APIs, Twilio, Redis, PostgreSQL)
  - PostGIS מוסיף מורכבות אך חיוני להתאמה גיאוגרפית מדויקת
  - spaCy לעומת מודל LLM – בחירה ב-spaCy לביצועים מהירים ועלות אפסית

metrics: "" # TODO: בדוק ידנית

faq:
  - q: "אילו שפות הבוט תומך?"
    a: "עברית, ערבית ואנגלית – עם זיהוי אוטומטי של שפת המשתמש."
  - q: "איך המערכת מתאימה דיווח לארגון?"
    a: "לפי מיקום גיאוגרפי (PostGIS) – מחפשת ארגונים בטווח מוגדר מנקודת הדיווח."
---
