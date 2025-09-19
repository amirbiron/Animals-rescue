# בוט חילוץ בעלי חיים 🐕🚑
> **מערכת אוטומטית לדיווח ושיגור חילוץ בעלי חיים**

מערכת מקיפה לניהול פעולות חילוץ בעלי חיים דרך ממשק בוט טלגרם, עם התראות אוטומטיות לארגונים, תמיכה בריבוי שפות ולוח בקרה למנהלים.

## 🎯 סקירה כללית
בוט החילוץ מאפשר לאזרחים לדווח במהירות על בעלי חיים במצוקה דרך ממשק טלגרם ידידותי.  
המערכת מעבדת את הדיווחים באופן אוטומטי, מבצעת התאמה גיאוגרפית לארגונים רלוונטיים, שולחת התראות לארגוני החילוץ ומספקת כלי ניהול מקיפים למנהלים.

### תכונות עיקריות
- **📱 ממשק טלגרם** – דיווח קל עם תמונות, מיקום ותיאור  
- **🌍 תמיכה בריבוי שפות** – עברית, ערבית ואנגלית עם זיהוי אוטומטי של השפה  
- **📍 שירותי מיקום** – שילוב Google Places/Geocoding לניהול מדויק של מיקומים  
- **🚨 התראות אוטומטיות** – מייל וטלגרם לארגונים רלוונטיים  
- **🧠 עיבוד שפה טבעית (NLP)** – ניתוח טקסט אוטומטי לזיהוי דחיפות וסיווג תוכן  
- **👑 לוח בקרה למנהלים** – ממשק ניהול מלא למשתמשים, ארגונים ודיווחים  
- **⚡ עיבוד רקע** – עיבוד משימות אסינכרוני עם Redis/RQ  
- **📊 אנליטיקה וניטור** – מעקב בזמן אמת על בריאות המערכת וסטטיסטיקות  

## 🏗️ ארכיטקטורה

### רכיבי ליבה
- **FastAPI REST API** – שרת האפליקציה הראשי עם תמיכה ב־async  
- **בוט טלגרם** – ממשק משתמש לשליחת דיווחים ואינטראקציות  
- **מסד נתונים PostgreSQL** – אחסון עיקרי עם PostGIS לנתוני מיקום  
- **Redis** – קאשינג, ניהול סשנים ותורי משימות  
- **RQ Workers** – עיבוד משימות רקע  
- **שירות SMTP/Email** – התראות במייל  
- **Google APIs** – חיפוש מקומות ושירותי Geocoding  

### טכנולוגיות
- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0 (async)  
- **Database**: PostgreSQL עם PostGIS  
- **Cache & Queue**: Redis עם RQ  
- **Framework לבוט**: python-telegram-bot 22.4+  
- **APIs חיצוניים**: Google Places, Google Geocoding  
- **ניטור**: Prometheus, לוגים מובנים  
- **שפות**: עברית, ערבית, אנגלית (תמיכה RTL/LTR)  

## 🚀 התחלה מהירה

### דרישות מוקדמות
- Python 3.12+  
- PostgreSQL 12+ עם PostGIS  
- Redis 6+  
- טוקן לבוט טלגרם ([יצירה כאן](https://t.me/BotFather))  
- מפתחות API של Google (Places & Geocoding)  

### התקנה
1. שכפול הריפו  
2. יצירת סביבת וירטואלית  
3. התקנת תלויות  
4. הגדרת משתני סביבה (`.env`)  
5. אתחול מסד הנתונים והרצת מיגרציות  
6. הפעלת השירותים: שרת API, Workers, Scheduler (אופציונלי)  

### התקנה עם Docker (חלופה)
- `docker-compose up --build`  
- `docker-compose exec api alembic upgrade head`  

## ⚙️ קונפיגורציה

יצירת קובץ `.env` עם משתנים נדרשים:  
- הגדרות אפליקציה  
- מסד נתונים PostgreSQL  
- Redis  
- בוט טלגרם + Webhook  
- Google API Keys  
- הגדרות SMTP  

משתנים אופציונליים:  
- אחסון S3/R2  
- ניטור עם Sentry  
- מגבלות שימוש ודגלי פיצ’רים  

## 📖 שימוש

### למשתמשי קצה (בטלגרם)
- התחלת שיחה עם הבוט  
- `/start` להפעלה  
- `/new_report` לפתיחת דיווח  
- העלאת תמונות, מיקום, תיאור, רמת דחיפות וסוג בעל חיים  

### לארגונים
- התראות בטלגרם עם כפתורי פעולה  
- מייל עם פרטים מלאים  
- לוח בקרה לניהול דיווחים  

### למנהלים
- גישה ללוח הבקרה (`/admin`)  
- ניהול משתמשים וארגונים  
- ניטור דיווחים וסטטיסטיקות  
- ניהול מערכת ותצורה  

## 🗂️ תיעוד API
- **Swagger UI**: http://localhost:8000/docs  
- **ReDoc**: http://localhost:8000/redoc  

דוגמאות Endpoints:  
- דיווחים: `POST /api/v1/reports/`, `GET /api/v1/reports/{id}`  
- מערכת: `/health`, `/metrics`  
- מנהל: `/admin/`, `/admin/stats`  

## 🔧 פיתוח

### מבנה פרויקט
- `app/api/v1/` – נתיבי FastAPI  
- `app/bot/` – טיפולי בוט טלגרם  
- `app/core/` – תצורה, קאש, אבטחה  
- `app/models/` – מודלים של SQLAlchemy  
- `app/services/` – שירותים חיצוניים (מייל, גוגל, NLP)  
- `app/workers/` – משימות רקע  
- `app/admin/` – לוח בקרה  
- `main.py` – נקודת כניסה  

### בדיקות
- התקנת תלויות dev  
- `pytest` להרצת בדיקות  
- `pytest --cov=app tests/` עם כיסוי  

### מיגרציות DB
- יצירת מיגרציה: `alembic revision --autogenerate`  
- החלה: `alembic upgrade head`  
- חזרה: `alembic downgrade -1`  

### הוספת שפות חדשות
- הוספה ל־`SUPPORTED_LANGUAGES`  
- יצירת קובץ תרגום ב־`app/translations/`  
- עדכון `i18n.py` אם נדרש  

## 📊 ניטור ותצפיות

### Health Checks
- API: `/health`  
- DB, Redis, Workers, Google APIs, Email  

### Metrics
- זמני תגובה, עומס, סטטיסטיקות Redis, סטטיסטיקות Workers  

### Logging
- JSON מובנה  
- אינטגרציה עם Sentry  
- Audit Logging  
- ניטור ביצועים  

## 🚀 פריסה
4. **בוט טלגרם (Telegram Bot)**
   - יש להגדיר את משתני הסביבה הבאים:
     - `TELEGRAM_BOT_TOKEN` – הטוקן שקיבלת מ־[BotFather](https://t.me/BotFather).
     - `WEBHOOK_HOST` – הדומיין הציבורי של השירות ב־Render (למשל `https://animal-rescue.onrender.com`).
     - `TELEGRAM_WEBHOOK_SECRET` – מחרוזת סודית לאימות בקשות webhook (מומלץ להגדיר ידנית).

   - לאחר הפריסה יש להריץ פקודה לקביעת ה־webhook:
     ```bash
     curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
          -d "url=$WEBHOOK_HOST/telegram/webhook?secret_token=$TELEGRAM_WEBHOOK_SECRET"
     ```

   - לבדיקה:
     ```bash
     curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
     ```

### פריסה ב־Render

ב־[Render](https://render.com/) יש להקים שני שירותים עיקריים:

1. **Web Service (שירות אינטרנטי)**  
   - מיועד להרצת FastAPI (ה־API הראשי + Webhook של טלגרם).  
   - **Build Command**:  
     ```bash
     pip install -r requirements.txt
     ```  
   - **Start Command**:  
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port 10000
     ```  

2. **Background Worker (וורקר ברקע)**  
   - מיועד להריץ את ה־RQ Workers שמטפלים במשימות רקע.  
   - **Build Command**:  
     ```bash
     pip install -r requirements.txt
     ```  
   - **Start Command**:  
     ```bash
     rq worker -u $REDIS_URL default alerts maintenance external
     ```  

3. **שירותי צד ג׳ מנוהלים**  
   - מומלץ להוסיף גם **Redis** ו־**PostgreSQL** כשירותים מנוהלים ישירות מ־Render.  
   - את פרטי ההתחברות מגדירים במשתני הסביבה:  
     - `DATABASE_URL` למסד הנתונים  
     - `REDIS_URL` ל־Redis  

> ⚠️ הערה: ניתן להגדיר שירותי Redis/Postgres גם מחוץ ל־Render, אך הפתרון המובנה שלהם מקל על תחזוקה וסקיילינג.

### משתני סביבה לפרודקשן
- `ENVIRONMENT=production`  
- `DATABASE_URL`, `REDIS_URL` וכו’  

### ארכיטקטורה מומלצת
- Load Balancer (nginx)  
- מספר מופעי FastAPI  
- PostgreSQL  
- Redis + Workers  

### שיקולי סקיילינג
- שרתי API – סקייל אופקי  
- Workers – לפי עומס  
- DB – רפליקות קריאה  
- Redis Cluster  

## 🔐 אבטחה
- אימות JWT  
- הרשאות לפי תפקידים (Reporter, Org Staff, Admin וכו’)  
- אימות משתמשי טלגרם  
- Rate limiting  
- הגנה ב־ORM מול SQL Injection  
- סיסמאות עם bcrypt  
- הצפנת HTTPS בפרודקשן  

## 🤝 תרומה
1. Fork  
2. יצירת ענף  
3. Commit  
4. Push  
5. Pull Request  

הנחיות פיתוח:  
- PEP8  
- Type hints  
- Docstrings  
- בדיקות לכל פיצ’ר חדש  
- עדכון תיעוד  

## 📄 רישיון
הפרויקט תחת MIT License  

## 📞 תמיכה
- תיעוד בריפו ובקוד  
- Issues בגיטהאב  
- Discussions בקהילה  

## ❗ פתרון בעיות נפוצות
- בעיות DB: בדיקת PostgreSQL ורצת PSQL  
- Redis: `redis-cli ping`  
- Webhook של טלגרם: `getWebhookInfo` או `setWebhook`  
- Workers: בדיקת סטטוס, ריסטארט עם docker-compose  

---

**נבנה באהבה ❤️ עבור ארגוני רווחת בעלי חיים ומתנדבי חילוץ**  
> "גדולתה של אומה נמדדת ביחס שלה לבעלי החיים." – מהטמה גנדי
