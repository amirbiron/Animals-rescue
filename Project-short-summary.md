# בוט חילוץ בעלי חיים

**ריפו:** [amirbiron/Animals-rescue](https://github.com/amirbiron/Animals-rescue)
**סטטוס:** פעיל

מערכת מקיפה לניהול פעולות חילוץ בעלי חיים דרך בוט טלגרם – דיווח, התאמה גיאוגרפית לארגונים, התראות אוטומטיות ולוח בקרה למנהלים.

## פיצ'רים מרכזיים
- ממשק טלגרם לדיווח עם תמונות, מיקום ותיאור
- תמיכה בעברית, ערבית ואנגלית עם זיהוי שפה אוטומטי
- התאמה גיאוגרפית (PostGIS) של דיווחים לארגוני חילוץ
- התראות מייל, טלגרם, SMS ו-WhatsApp לארגונים
- NLP (spaCy) לזיהוי דחיפות וסיווג אוטומטי
- לוח בקרה מלא למנהלים עם אנליטיקה

## Tech Stack
Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL+PostGIS, Redis+RQ, python-telegram-bot, Google APIs, spaCy, Twilio, Prometheus, Docker

## לינקים
- Live / Demo: אין (self-hosted) <!-- TODO: בדוק ידנית -->
- Docs: Swagger UI ב-`/docs`

## מה עשיתי
פיתוח מלא – ארכיטקטורה, FastAPI backend, אינטגרציית Telegram/Google/Twilio, מערכת NLP, לוח בקרה, workers אסינכרוניים, ו-deployment עם Docker.
