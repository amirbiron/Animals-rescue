# 📁 מבנה הפרויקט - Animals Rescue

## 🎯 סקירה כללית
מסמך זה מספק מבט מקיף על מבנה הקבצים והתיקיות בפרויקט Animals-rescue, עם תיאור מפורט של כל רכיב ותפקידו במערכת.

---

## 🏗️ מבנה התיקיות הראשי

### 📋 CI/CD ואוטומציה
| נתיב | תיאור |
|------|--------|
| `.github/workflows` | קובצי YAML לאוטומציה ב-GitHub Actions |
| ├── `ci.yml` | הרצת בדיקות ו-lint בכל קומיט |
| ├── `docs.yml` | בניית אתר התיעוד עם MkDocs |
| └── `pages.yml` | דיפלוי אוטומטי ל-GitHub Pages |

---

## 🚀 ליבת האפליקציה

### 🎛️ נקודת כניסה וניהול
| נתיב | תיאור |
|------|--------|
| `app/main.py` | נקודת הכניסה הראשית - מגדיר FastAPI, מחבר נתיבי API, מפעיל מטלות רקע ומטפל ב-CORS/Logging |
| `admin/routes.py` | API לממשק הניהול - ניהול משתמשים וארגונים, מעקב דיווחים, סטטיסטיקות וניטור מערכת |

### 🔌 API Endpoints (v1)
| נתיב | תיאור |
|------|--------|
| `app/api/v1/` | תיקיית נקודות הקצה של גרסת ה-API |
| ├── `api.py` | מאגד את כל הנתיבים |
| ├── `docs_route.py` | מגיש דפי תיעוד |
| ├── `docs_static.py` | מגיש קבצים סטטיים לתיעוד |
| ├── `reports.py` | Endpoints לקבלת וניהול דוחות |
| └── `twilio_webhook.py` | מטפל בבקשות SMS/WhatsApp נכנסות |

### 🤖 בוט טלגרם
| נתיב | תיאור |
|------|--------|
| `app/bot/handlers.py` | Handlers של הבוט - התחלת שיחה, קבלת דיווח, ניהול מספרי טלפון, מחיקת דיווחים |
| `app/bot/webhook.py` | FastAPI endpoint לקבלת עדכונים מטלגרם והעברתם ל-handlers |

---

## ⚙️ רכיבי ליבה (Core)

| נתיב | תיאור |
|------|--------|
| `app/core/cache.py` | מנגנוני זיכרון מטמון ו-Rate Limiting עם Redis |
| `app/core/config.py` | ניהול הגדרות עם Pydantic - משתני סביבה, בסיס נתונים, מפתחות |
| `app/core/exceptions.py` | חריגות מותאמות אישית - הרשאות, Rate-Limit, שגיאות שירותים |
| `app/core/i18n.py` | תרגום והתאמת שפה - טעינת JSON בשפות שונות |
| `app/core/rate_limit.py` | בקרת קצב - `check_rate_limit` ו-`RateLimitExceeded` |
| `app/core/security.py` | כלי אבטחה - JWT, גיבוב סיסמאות, בדיקת הרשאות |

---

## 💾 מודלים ובסיס נתונים

| נתיב | תיאור |
|------|--------|
| `app/models/database.py` | מודל SQLAlchemy 2.0 (async) - טבלאות ארגונים, דיווחים, משתמשים, טריגרים ו-Audit Trail |

---

## 🔧 שירותים (Services)

| נתיב | תיאור |
|------|--------|
| `app/services/email.py` | שליחת מיילים והתראות |
| `app/services/file_storage.py` | העלאה והורדה של קבצים לענן |
| `app/services/geocoding.py` | קידוד/פענוח כתובות ומיקום גיאוגרפי |
| `app/services/google.py` | אינטגרציה עם Google Places לאיתור ארגונים |
| `app/services/nlp.py` | ניתוח טקסט - זיהוי מילות מפתח בדיווחים |
| `app/services/serpapi.py` | חיפוש באינטרנט דרך SerpAPI |
| `app/services/sms.py` | שליחת SMS עם Twilio |
| `app/services/telegram_alerts.py` | שליחת הודעות טלגרם לצוותי הצלה |
| `app/services/whatsapp.py` | שליחת WhatsApp דרך Twilio Business API |

---

## 📝 תבניות ותרגומים

| נתיב | תיאור |
|------|--------|
| `app/templates/emails/` | תבניות HTML למיילים |
| └── `new_report_alert.html` | תבנית התראה על דיווח חדש |
| `app/translations/` | קבצי תרגום JSON |
| ├── ערבית | תרגומים לערבית |
| ├── אנגלית | תרגומים לאנגלית |
| └── עברית | תרגומים לעברית |

---

## 👷 Workers ומשימות רקע

| נתיב | תיאור |
|------|--------|
| `app/workers/jobs.py` | עבודות אסינכרוניות ב-RQ - שליחת הודעות, סינכרון ערוצי התראה |
| `app/workers/manager.py` | ניהול workers - הפעלה, לוח זמנים, ניטור בריאות, graceful shutdown |

---

## 📚 תיעוד

### תיעוד ציבורי
| נתיב | תיאור |
|------|--------|
| `docs/` | תיקיית התיעוד הראשית |
| ├── `getting-started.md` | מדריך התחלה מהירה |
| ├── `quickstart.md` | התחלה מהירה |
| ├── `architecture.md` | ארכיטקטורת המערכת |
| ├── `admin-guide.md` | מדריך למנהלי מערכת |
| ├── `api-reference.md` | תיעוד API |
| ├── `dev-guide.md` | מדריך למפתחים |
| ├── `faq.md` | שאלות נפוצות |
| └── `README-docs.md` | תוכן עניינים ומבנה התיעוד |

### תיעוד פנימי
| נתיב | תיאור |
|------|--------|
| `docs_archive/` | ארכיון מסמכי אפיון ותכנון פנימיים |
| ├── `Genspark-Advice.md` | עצות ומלצות |
| ├── `data-collection-implementation.md` | יישום איסוף נתונים |
| └── `README.md` | הסבר על המסמכים הפנימיים |

---

## 🛠️ סקריפטים וכלים

### סקריפטי Python
| נתיב | תיאור |
|------|--------|
| `scripts/collect_organizations.py` | איסוף נתונים על עמותות/מקלטים והמרה ל-CSV |

### סקריפטי SQL
| נתיב | תיאור |
|------|--------|
| `scripts/initial_data.sql` | טעינת נתוני בסיס - ארגונים ומשתמשים |
| `scripts/update_alert_channels.sql` | עדכון ערוצי התראה לארגונים - יצירת מערך text[] מ-primary_phone ו-phones |

### סקריפטי Bash
| נתיב | תיאור |
|------|--------|
| `scripts/serve_docs.sh` | בניית והרצת אתר התיעוד לוקלית |
| `build_docs.sh` | בניית אתר התיעוד עם MkDocs |
| `install_docs.sh` | התקנת MkDocs במערכת |

---

## 🧪 בדיקות

| נתיב | תיאור |
|------|--------|
| `tests/` | תיקיית הבדיקות הראשית |
| ├── `test_admin_flows.py` | בדיקת זרימות ניהול בבוט |
| ├── `test_i18n.py` | בדיקת מערכת התרגומים |
| ├── `test_import_cities.py` | בדיקת ייבוא ערים |
| ├── `test_report_flow.py` | בדיקת זרימת דיווח |
| └── `test_security_docs.py` | בדיקות אבטחה |

---

## ⚙️ קובצי הגדרות

| נתיב | תיאור |
|------|--------|
| `.cursorrules` | הנחיות למפתחים עם Cursor IDE - כתיבה ברורה, דוקסטינג בעברית, pytest fixtures |
| `.env.example` | דוגמה להגדרות סביבת עבודה - ENVIRONMENT, DEBUG, API_V1_PREFIX, בסיס נתונים |
| `.python-version` | סקריפט התקנת Python ותלויות |
| `pytest.ini` | קונפיגורציה ל-pytest - asyncio_default_fixture_loop_scope=function |
| `mkdocs.yml` | קונפיגורציית MkDocs - שם האתר, תבנית Material, RTL, עץ ניווט |

---

## 📖 מסמכי הדרכה

| נתיב | תיאור |
|------|--------|
| `README.md` | תיאור ראשי - מטרות הפרויקט, פונקציות עיקריות, ארכיטקטורה, התקנה |
| `DOCUMENTATION.md` | מדריך הפעלת אתר תיעוד ב-GitHub Pages |
| `DEPLOY_DOCS_RENDER.md` | מדריך פרסום אתר תיעוד ב-Render |
| `PR_DESCRIPTION_HE.md` | תבנית בעברית לתיאור Pull Request |
| `SECURITY_DOCS.md` | הסבר על פגיעות Path-Traversal ופתרונות אבטחה |

---

## 🔍 סיכום

הפרויקט Animals-rescue בנוי בארכיטקטורה מודולרית עם הפרדה ברורה בין:
- **ליבת האפליקציה** - FastAPI, בוט טלגרם, API
- **שירותים** - אינטגרציות עם שירותים חיצוניים
- **רכיבי תשתית** - cache, config, security
- **תיעוד מקיף** - למשתמשים ולמפתחים
- **בדיקות** - כיסוי מלא של הפונקציונליות
- **אוטומציה** - CI/CD עם GitHub Actions

המבנה מאפשר תחזוקה קלה, הרחבה והוספת פיצ'רים חדשים בצורה מסודרת ומאורגנת.