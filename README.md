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

### פריסה ב־Render (מעודכן)

ב־Render יש להקים שני שירותים עיקריים + שירותים מנוהלים:

1) Web Service (FastAPI + Webhook טלגרם)
- Build Command:
```bash
pip install -r requirements.txt
```
- Start Command:
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
- Port: השאירו ברירת מחדל של Render (המשתנה $PORT מוזרק אוטומטית)

משתני סביבה עיקריים (Environment):
- TELEGRAM_BOT_TOKEN
- WEBHOOK_HOST (למשל: https://<your-app>.onrender.com)
- TELEGRAM_WEBHOOK_SECRET (מחרוזת אקראית)
- DATABASE_URL (Postgres)
- REDIS_URL (Redis)
- ENVIRONMENT=production
- ENABLE_WORKERS=false (לשירות ה-Web)
- GOOGLE_PLACES_API_KEY (חיוני)
- GOOGLE_GEOCODING_API_KEY (אופציונלי; אם לא, נשתמש ב-Places)

2) Background Worker (RQ Workers + Scheduler)
- Build Command:
```bash
pip install -r requirements.txt
```
- Start Command:
```bash
python -c "from app.workers.manager import run_workers_cli; run_workers_cli()"
```

משתני סביבה לשירות ה-Worker:
- DATABASE_URL, REDIS_URL (כמו ב-Web)
- ENVIRONMENT=production
- ENABLE_WORKERS=true
- WORKER_PROCESSES=2 (לפי עומס)
- WORKER_TIMEOUT=300 (אופציונלי)
- GOOGLE_PLACES_API_KEY / GOOGLE_GEOCODING_API_KEY (לסנכרוני Places/Geocoding)

3) שירותים מנוהלים
- Render PostgreSQL → חשפו `DATABASE_URL`
- Render Redis → חשפו `REDIS_URL`

הערות חשובות:
- Webhook: המערכת מגדירה Webhook אוטומטית אם `WEBHOOK_HOST` מוגדר; ודאו ש-HTTPS פעיל וש-`TELEGRAM_WEBHOOK_SECRET` מוגדר.
- יצירת טבלאות (אופציונלי, אם אין Alembic): Post-deploy Command חד-פעמי:
```bash
python -c "import asyncio; from app.models.database import create_tables; asyncio.run(create_tables())"
```
- סקיילינג: 
  - Web: הגדילו instances לפי עומס
  - Workers: הגדילו WORKER_PROCESSES/Instances לפי תורים

בדיקות זריזות לאחר פריסה:
- /health מחזיר תקין
- /api/v1/openapi.json נטען (אם SHOW_DOCS דלוק)
- בוט מגיב ל-/start
- לחצן "🏢 ניהול ארגונים" מציג אפשרויות ייבוא וסנכרון

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
## 🧩 בדיקת תלויות בזמן עלייה (Startup Self-check)

האפליקציה מבצעת בדיקת תלויות בתחילת ה־startup כדי לעצור מוקדם עם הודעה ברורה אם חסרה חבילה קריטית.

- **איפה זה נמצא**: `app/main.py`, פונקציה `_check_runtime_dependencies`
- **מה נבדק כרגע**: `tenacity`, `httpx`, `redis`, `rq`, `telegram` (ניתן להרחיב בהמשך)
- **מה קורה אם חסר**: עולה שגיאה עם לוג ברור שמפרט אילו חבילות חסרות ומה לעשות

דוגמת לוג לשגיאה:
```text
❌ Missing required Python packages missing=['tenacity']
fix="Add the missing packages to requirements.txt and rebuild/redeploy. On Render: trigger a deploy to install updated dependencies."
```

### איך מתקנים בפרודקשן (Render)
- ודאו שהחבילה מופיעה ב־`requirements.txt` (למשל: `tenacity==9.0.0`).
- בצעו Commit + Push.
- ב־Render: בצעו Redeploy. מומלץ "Manual Deploy → Clear build cache & deploy" כדי להבטיח התקנה נקייה.
- ה־Build מריץ `pip install -r requirements.txt`, ואז השרת יעלה ללא השגיאה.

### איך מתקנים בסביבה מקומית
הימנעו מהתקנות גלובליות (PEP 668). עבדו בתוך venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import tenacity; print(tenacity.__version__)"
```

טיפים:
- אם יצירת venv נכשלת בגלל ensurepip, התקינו את חבילת המערכת המתאימה (בדביאן/אובונטו):
  ```bash
  sudo apt-get update && sudo apt-get install -y python3-venv
  ```
- אם נתקלתם ב־PEP 668: אל תשתמשו ב־`--break-system-packages`; עבדו בתוך venv.

### הרחבת הבדיקה
כדי להוסיף חבילות נוספות לבדיקה, הרחיבו את הרשימה ב־`_check_runtime_dependencies` (למשל: `"googlemaps"`, `"httpx"`, `"redis"`).
הרישום של הראוטרים מתבצע אחרי הבדיקה, כך שחבילות חסרות יזוהו מוקדם עם הודעה ידידותית.
- בעיות DB: בדיקת PostgreSQL ורצת PSQL  
- Redis: `redis-cli ping`  
- Webhook של טלגרם: `getWebhookInfo` או `setWebhook`  
- Workers: בדיקת סטטוס, ריסטארט עם docker-compose  

## 📂 Project Docs & Tools

בפרויקט קיימים מסמכים וסקריפטים שימושיים לניהול ושיפור המערכת:

- `docs/data-collection-implementation.md`  
  מדריך טכני ליישום – כולל מבנה טבלאות, מודלים, סקריפטים לאיסוף ואימות נתונים.

- `docs/next-steps-playbook.md`  
  מדריך למפתחים – צעדים מיידיים, תיקונים בקוד, בדיקות קריטיות ושיתופי פעולה מומלצים.

- `docs/vision-and-improvement.md`  
  מסמך שיפור מקיף – מפת דרכים, אתגרים צפויים, עלויות משוערות ושיפורים עתידיים.

- `docs/seed/organizations_seed.csv`  
  נתוני seed ראשוניים של ארגונים (שם, כתובת, טלפון, מייל וכו׳) לטעינה במסד או בדיקות.

- `scripts/collect_organizations.py`  
  סקריפט איסוף אוטומטי מ־Google Places או מקובץ CSV ידני.  
  שימוש:  
  ```bash
  python scripts/collect_organizations.py --source google --cities "תל אביב,ירושלים"
  python scripts/collect_organizations.py --source manual --file docs/seed/organizations_seed.csv
  ```

- `scripts/initial_data.sql`  
  סקריפט SQL לטעינת נתוני ארגונים ראשוניים ישירות למסד PostgreSQL.  
  שימוש:
  ```bash
  psql -U postgres -d animal_rescue -f scripts/initial_data.sql
  ```

---

**נבנה באהבה ❤️ עבור ארגוני רווחת בעלי חיים ומתנדבי חילוץ**  
> "גדולתה של אומה נמדדת ביחס שלה לבעלי החיים." – מהטמה גנדי
