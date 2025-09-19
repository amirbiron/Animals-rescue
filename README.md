🐕🚑 בוט חילוץ בעלי חיים

> מערכת אוטומטית לדיווח וחילוץ בעלי חיים



מערכת מקיפה לניהול פעולות חילוץ בעלי חיים דרך ממשק טלגרם, כולל שליחת התראות אוטומטיות לארגונים, תמיכה בריבוי שפות ולוח בקרה למנהלים.

🎯 סקירה

הבוט מאפשר לאזרחים לדווח במהירות על בעלי חיים במצוקה דרך ממשק טלגרם ידידותי.
המערכת מעבדת את הדיווחים אוטומטית, מבצעת התאמה לארגוני חילוץ לפי מיקום, שולחת התראות רלוונטיות, ומספקת כלי ניהול מתקדמים למנהלים.

תכונות עיקריות

📱 ממשק טלגרם – דיווח קל עם תמונות, מיקום ותיאור

🌍 תמיכה רב־לשונית – עברית, ערבית ואנגלית עם זיהוי שפה אוטומטי

📍 שירותי מיקום – שילוב Google Places/Geocoding לאיתור מדויק

🚨 התראות אוטומטיות – מייל וטלגרם לארגונים רלוונטיים

🧠 עיבוד שפה טבעית (NLP) – ניתוח טקסט לזיהוי דחיפות וסיווג

👑 לוח בקרה למנהלים – ניהול משתמשים, ארגונים ודיווחים

⚡ עיבוד ברקע – משימות אסינכרוניות עם Redis/RQ

📊 ניטור וסטטיסטיקות – מעקב בריאות המערכת בזמן אמת


🏗️ ארכיטקטורה

רכיבים מרכזיים

FastAPI REST API – שרת האפליקציה

בוט טלגרם – ממשק משתמש לדיווחים

PostgreSQL – מסד נתונים עם PostGIS למידע גיאוגרפי

Redis – קאש, ניהול סשנים ותורי משימות

RQ Workers – עיבוד משימות ברקע

SMTP/Email – שליחת התראות במייל

Google APIs – חיפוש מקומות וגיאוקודינג


טכנולוגיות

Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async)

Database: PostgreSQL + PostGIS

Cache & Queue: Redis + RQ

בוט: python-telegram-bot 22.4+

APIs חיצוניים: Google Places, Geocoding

ניטור: Prometheus, לוגים מובנים

שפות: עברית, ערבית, אנגלית (RTL/LTR)


🚀 התקנה מהירה

דרישות מקדימות

Python 3.12+

PostgreSQL 12+ עם PostGIS

Redis 6+

טוקן בוט טלגרם

מפתחות Google API


צעדים

1. שכפול הריפו


2. יצירת venv והפעלתו


3. התקנת תלות


4. הגדרת משתני סביבה (.env)


5. אתחול DB עם Alembic


6. הפעלת שרת API, Workers ומתזמן (אופציונלי)



Docker (אלטרנטיבה)

docker-compose up --build && docker-compose exec api alembic upgrade head

⚙️ קונפיגורציה

קובץ .env כולל:

פרטי אפליקציה (SECRET_KEY, ENVIRONMENT וכו’)

מסד נתונים (POSTGRES_*)

Redis (REDIS_*)

בוט טלגרם (TELEGRAM_BOT_TOKEN, WEBHOOK_*)

Google APIs

מייל SMTP

אפשרויות נוספות: S3, Sentry, מגבלות דיווח


📖 שימוש

משתמשים

/start – התחלה

/new_report – דיווח חדש

העלאת תמונה, מיקום, תיאור, דחיפות וסוג חיה


ארגונים

התראות בטלגרם

מייל HTML מפורט

דשבורד ניהול


מנהלים

ניהול משתמשים וארגונים

ניטור דיווחים וסטטיסטיקות

הגדרות מערכת


🗂️ API

Swagger: /docs

ReDoc: /redoc

נקודות עיקריות: /api/v1/reports, /health, /metrics, /admin


🔧 פיתוח

מבנה פרויקט: api/, bot/, core/, models/, services/, workers/, admin/

בדיקות: pytest

מיגרציות DB: Alembic

הוספת שפות: app/translations/{lang}.json


📊 ניטור

Health: API, DB, Redis, Workers, שירותי חוץ

Metrics: Prometheus (/metrics)

לוגים: JSON עם Sentry


🚀 דיפלוי

ENVIRONMENT=production

ארכיטקטורה מומלצת: Load Balancer + FastAPI + DB + Redis + Workers

סקיילינג: שרתי API, Workers, Redis Cluster, רפליקות DB


🔐 אבטחה

JWT + בקרת תפקידים

אימות משתמשי טלגרם

Rate limiting

הצפנת סיסמאות (bcrypt)

HTTPS בפרודקשן


🤝 תרומה

1. Fork


2. Branch


3. Commit


4. Pull Request



הנחיות: PEP8, type hints, docstrings, בדיקות, עדכון תיעוד.

📄 רישוי

רישיון MIT.

📞 תמיכה

תיעוד README

Issues ו-Discussions ב-GitHub

פתרון תקלות נפוצות (DB, Redis, Webhook, Workers)



---

נבנה באהבה ❤️ למען בעלי חיים ומתנדבי חילוץ

