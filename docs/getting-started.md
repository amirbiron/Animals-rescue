# התחלה מהירה 🚀

מדריך זה יעזור לך להקים את המערכת תוך 5-10 דקות בסביבת הפיתוח המקומית שלך.

## דרישות מוקדמות

### תוכנות נדרשות

| רכיב | גרסה מינימלית | בדיקה |
|------|----------------|--------|
| Python | 3.12+ | `python --version` |
| PostgreSQL | 12+ עם PostGIS | `psql --version` |
| Redis | 6+ | `redis-cli --version` |
| Git | 2.0+ | `git --version` |

### מפתחות API נדרשים

!!! warning "חשוב"
    יש להשיג את המפתחות הבאים **לפני** ההתקנה

- **בוט טלגרם** - [יצירת בוט חדש](https://t.me/BotFather)
- **Google APIs** - [Google Cloud Console](https://console.cloud.google.com/)
  - Places API
  - Geocoding API
- **Twilio** (אופציונלי) - לשליחת SMS/WhatsApp
- **SerpAPI** (אופציונלי) - להעשרת נתוני ארגונים

## שלב 1: שכפול הפרויקט

```bash
# שכפול הריפו
git clone https://github.com/animal-rescue-bot/animal-rescue-bot.git
cd animal-rescue-bot

# יצירת סביבה וירטואלית
python3 -m venv venv
source venv/bin/activate  # ב-Windows: venv\Scripts\activate
```

## שלב 2: התקנת תלויות

```bash
# התקנת חבילות Python
pip install --upgrade pip
pip install -r requirements.txt

# התקנת חבילות פיתוח (אופציונלי)
pip install -r requirements-dev.txt
```

## שלב 3: הגדרת משתני סביבה

### יצירת קובץ .env

```bash
# העתקת תבנית
cp .env.example .env

# עריכת הקובץ
nano .env  # או כל עורך אחר
```

### משתנים חיוניים

```env
# === הגדרות בסיסיות ===
ENVIRONMENT=development
DEBUG=true
SECRET_KEY=your-secret-key-here

# === מסד נתונים ===
DATABASE_URL=postgresql://user:password@localhost:5432/animal_rescue
# או לחלופין:
DB_HOST=localhost
DB_PORT=5432
DB_NAME=animal_rescue
DB_USER=your_user
DB_PASSWORD=your_password

# === Redis ===
REDIS_URL=redis://localhost:6379/0

# === בוט טלגרם ===
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_WEBHOOK_SECRET=random-secret-string

# === Google APIs ===
GOOGLE_PLACES_API_KEY=AIza...
GOOGLE_GEOCODING_API_KEY=AIza...

# === מייל (אופציונלי) ===
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=app-specific-password
SMTP_FROM=your-email@gmail.com
```

!!! tip "טיפ"
    השתמש ב-`python -c "import secrets; print(secrets.token_urlsafe(32))"` ליצירת מפתח סודי חזק

## שלב 4: הכנת מסד הנתונים

### יצירת מסד נתונים

```bash
# התחברות ל-PostgreSQL
psql -U postgres

# יצירת מסד נתונים
CREATE DATABASE animal_rescue;
CREATE USER your_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE animal_rescue TO your_user;

# הפעלת PostGIS (אופציונלי אך מומלץ)
\c animal_rescue
CREATE EXTENSION IF NOT EXISTS postgis;
\q
```

### הרצת מיגרציות

```bash
# יצירת טבלאות
alembic upgrade head

# או לחלופין (אם אין Alembic)
python -c "import asyncio; from app.models.database import create_tables; asyncio.run(create_tables())"
```

### טעינת נתונים ראשוניים

```bash
# טעינת ארגונים לדוגמה
psql -U your_user -d animal_rescue < scripts/initial_data.sql

# או דרך Python
python scripts/collect_organizations.py
```

## שלב 5: הפעלת השירותים

### הפעלת Redis

```bash
# בחלון טרמינל נפרד
redis-server
```

### הפעלת שרת הפיתוח

```bash
# הפעלת FastAPI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### הפעלת Workers (בחלון נפרד)

```bash
# הפעלת RQ Workers
python -c "from app.workers.manager import run_workers_cli; run_workers_cli()"

# או לחלופין
rq worker -u redis://localhost:6379 default alerts maintenance external
```

## שלב 6: הגדרת Webhook לטלגרם

### בסביבת פיתוח (ngrok)

```bash
# התקנת ngrok
# macOS: brew install ngrok
# Linux: snap install ngrok
# Windows: הורד מ-https://ngrok.com

# הפעלת ngrok
ngrok http 8000

# העתק את ה-URL (למשל: https://abc123.ngrok.io)
```

### הגדרת ה-Webhook

```bash
# הגדר את WEBHOOK_HOST ב-.env
WEBHOOK_HOST=https://abc123.ngrok.io

# הפעל מחדש את השרת

# או הגדר ידנית
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     -d "url=$WEBHOOK_HOST/telegram/webhook?secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## שלב 7: בדיקת המערכת

### בדיקת בריאות

```bash
# בדיקת API
curl http://localhost:8000/health

# תגובה צפויה:
{
  "status": "healthy",
  "services": {
    "database": "connected",
    "redis": "connected",
    "telegram": "connected"
  }
}
```

### בדיקת הבוט

1. פתח את הבוט בטלגרם
2. שלח `/start`
3. עקוב אחר ההוראות ליצירת דיווח

### גישה ללוח הבקרה

```
http://localhost:8000/admin
```

### תיעוד API

```
http://localhost:8000/docs     # Swagger UI
http://localhost:8000/redoc    # ReDoc
```

## 🐳 התקנה עם Docker (חלופה)

### שימוש ב-Docker Compose

```bash
# בניית הקונטיינרים
docker-compose build

# הפעלה
docker-compose up -d

# בדיקת לוגים
docker-compose logs -f

# הרצת מיגרציות
docker-compose exec api alembic upgrade head
```

### קובץ docker-compose.yml בסיסי

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/animal_rescue
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis

  worker:
    build: .
    command: python -c "from app.workers.manager import run_workers_cli; run_workers_cli()"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/animal_rescue
      - REDIS_URL=redis://redis:6379
    depends_on:
      - db
      - redis

  db:
    image: postgis/postgis:15-3.3
    environment:
      - POSTGRES_DB=animal_rescue
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

## 🔧 פתרון בעיות נפוצות

### בעיה: חיבור למסד נתונים נכשל

```bash
# בדוק שהשירות פועל
sudo systemctl status postgresql

# בדוק הרשאות
psql -U your_user -d animal_rescue -c "SELECT 1"
```

### בעיה: Redis לא זמין

```bash
# הפעל מחדש
redis-cli shutdown
redis-server

# בדוק חיבור
redis-cli ping
```

### בעיה: הבוט לא מגיב

```bash
# בדוק Webhook
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"

# מחק Webhook ישן
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/deleteWebhook"

# הגדר מחדש
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
     -d "url=$WEBHOOK_HOST/telegram/webhook?secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

### בעיה: חבילות Python חסרות

```bash
# בדוק שאתה בסביבה הווירטואלית
which python  # צריך להצביע על venv/bin/python

# התקן מחדש
pip install --force-reinstall -r requirements.txt
```

## 📝 הצעדים הבאים

✅ **המערכת פועלת!** עכשיו אתה יכול:

1. **[להוסיף ארגונים](admin-guide.md#adding-organizations)** - הגדרת ארגוני חילוץ באזור שלך
2. **[להגדיר התראות](admin-guide.md#notifications)** - קביעת ערוצי התראה ומדיניות
3. **[לבדוק את ה-API](api-reference.md)** - חקירת נקודות הקצה
4. **[להתחיל לפתח](dev-guide.md)** - הוספת תכונות חדשות

## 🆘 צריך עזרה?

- 📖 [שאלות נפוצות](faq.md)
- 🔧 [מדריך פתרון בעיות](troubleshooting.md)
- 💬 [קבוצת תמיכה בטלגרם](https://t.me/AnimalRescueDev)
- 🐛 [דיווח על באג](https://github.com/animal-rescue-bot/issues)

---

<div align="center">
  <strong>🎉 כל הכבוד! המערכת מוכנה לשימוש</strong>
</div>