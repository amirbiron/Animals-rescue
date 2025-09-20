# 📋 מסמך שיפור מקיף – Animal Rescue Bot

## 🎯 מטרת המסמך
הופך את הבוט ממוכנות טכנית למערכת מצילה חיים בפועל: בניית בסיס נתונים אמין של ארגונים עם פרטי קשר, הוספת מערכת התראות מדורגת, והגדרת תפעול וניטור.

---

## 🚨 הבעיה המרכזית
- אין כיום רשימת ארגונים (עמותות, וטרינרים, מקלטים) עם פרטי קשר.
- בלי טלפון/מייל/WhatsApp מאומתים – אין דרך להעביר התראות שמבשילות לפעולה.

---

## ✅ תוצאות מבוקשות
- MVP (חודש ראשון):
  - ≥ 200 ארגונים עם לפחות ערוץ קשר אחד מאומת (טלפון/מייל/WhatsApp)
  - זמן עד אישור ראשון (TTA) < 5 דקות
  - שיעור הצלחה ≥ 70%
- אחרי 3 חודשים: ≥ 500 ארגונים פעילים, דיווחים שבועיים רציפים
- אחרי 6 חודשים: כיסוי ארצי מלא, שיעור הצלחה ≥ 90%

---

## 🗺️ מפת דרכים (MVP קצר)
1. שבוע 1–2: איסוף ידני + הרשמה ל‑API (Google Places Details, SerpAPI, Overpass)
2. שבוע 3–4: בניית DB ראשוני (≥ 200), נרמול טלפונים (E.164), אימות בסיסי
3. שבוע 5–6: שילוב מערכת התראות (WhatsApp + SMS), לוגים ומדדים
4. שבוע 7–8: ניסויי שטח, מדרג הסלמה, שיפורי איכות נתונים

---

## 🧱 סכימת נתונים מינימלית

טבלאות חובה (PostgreSQL; הרחבה ל‑PostGIS בהמשך):

-- organizations: ישות ארגון
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  address TEXT,
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  verification_status TEXT CHECK (verification_status IN ('unverified','partial','verified')) DEFAULT 'unverified',
  last_verified_at TIMESTAMPTZ,
  preferred_channel TEXT CHECK (preferred_channel IN ('whatsapp','sms','email')),
  languages TEXT[],
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- contact_methods: ערוצי קשר לארגון
CREATE TABLE contact_methods (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('phone','email','whatsapp')),
  value TEXT NOT NULL,            -- טלפון בפורמט E.164, אימייל או מזהה WhatsApp
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  last_verified_at TIMESTAMPTZ,
  UNIQUE (organization_id, type, value)
);

-- incidents: דיווחי אירועים
CREATE TABLE incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  lat DOUBLE PRECISION NOT NULL,
  lon DOUBLE PRECISION NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','in_progress','closed')) DEFAULT 'open'
);

-- notification_attempts: ניסיונות התראה
CREATE TABLE notification_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('whatsapp','sms','email','voice')),
  attempt_num INT NOT NULL,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','sent','delivered','ack','failed')),
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  ack_at TIMESTAMPTZ,
  UNIQUE (idempotency_key)
);

-- sources: מקורות נתונים (API/קבצים/ידני)
CREATE TABLE sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('google_places','serpapi','osm','sheet','manual')),
  reference TEXT
);

-- organization_sources: קישור מזהים חיצוניים
CREATE TABLE organization_sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id TEXT NOT NULL,
  UNIQUE (source_id, external_id)
);
אינדקסים מומלצים:
- CREATE INDEX ON contact_methods (type, value);
- אם PostGIS פעיל: GEOGRAPHY(Point) בעמודת location (אופציונלי) + GIST.

---

## 🔎 איסוף והעשרה (Pipeline)
שלבים:
1. Ingest: משיכה מ‑Google Places Details (כולל Contact Data), SerpAPI, Overpass (OSM), וגיליונות/קבצים ידניים
2. Normalize: ניקוי שמות, נרמול טלפונים ל‑E.164, הסרת כפילויות לפי (טלפון/דומיין/שם+כתובת)
3. Enrich: גיאוקודינג (אם חסר), השלמת אתר/מייל, שעות פעילות, שפות
4. Verify: בדיקת טלפונים (Twilio Lookup), אימות אימייל (SMTP ping/שירות צד ג')
5. Score: דירוג אמינות מקור ועדכניות (last_verified_at, verified=true)
6. Upsert: עדכון/הכנסה עם source_id ו‑external_id לשחזור עקיבות

מקורות מומלצים:
- Google Places API → Place Details (כולל Contact Data fields) – חיוב לפי שדות
- SerpAPI (Google Maps) – לעיתים מחזיר טלפונים/אתרים בקלות
- Overpass (OSM) – amenity=veterinary, animal_shelter – איסוף ראשוני חינמי
- Google Sheet משותף – קליטה ידנית מאורגונים ומתנדבים

תבנית Seed: ראה docs/seed/organizations_seed.csv (עמודות חובה וכמה דוגמאות)

---

## 📣 מערכת התראות מדורגת

ערוצים: WhatsApp, SMS, Email (ובהמשך Voice).

מדרג ניסיונות (דוגמה):
- T+0: WhatsApp לארגונים הקרובים ביותר (N=3 בתוך רדיוס)
- T+2 דק: SMS לאותם ארגונים שלא אישרו
- T+5 דק: שיחה/Voice לארגון הראשי
- T+10 דק: מעבר לארגונים חלופיים (נוספים ברדיוס/אזור סמוך)

Idempotency:
- מפתח ייחודי: incident_id + organization_id + channel + attempt_num
- לוג תוצאות: sent_at, delivered_at, ack_at, failed_reason

העדפות:
- preferred_channel, שעות פעילות, שפות, חלון שקט, קיבולת זמינה

סטטוסים:
- אירוע: open → in_progress → closed
- ניסיון: queued → sent → delivered → ack | failed

תבניות הודעה (רמזים):
- כל הודעה כוללת קישור ביטול/הסרה ופרטי קשר חזרה

---

## ⚖️ תאימות ואתיקה
- opt‑in מארגונים ככל שניתן; opt‑out מובנה בכל הודעה
- כיבוד שעות שקט (קונפיגורציה), קצב שליחה מוגבל (Rate Limit)
- שמירת לוגים בהתאם לפרטיות; מחיקת נתונים לפי בקשה
- שימוש ב‑WhatsApp/Twilio בתבניות מאושרות בלבד

---

## 🛠️ תצורה (ENV) מוצעת
DATABASE_URL=
GOOGLE_PLACES_API_KEY=
SERPAPI_KEY=
OVERPASS_URL=https://overpass-api.de/api/interpreter
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=+9725XXXXXXXX
WHATSAPP_FROM=whatsapp:+9725XXXXXXXX
DEFAULT_RADIUS_KM=15
QUIET_HOURS=22:00-07:00
MAX_ATTEMPTS_PER_ORG=3
---

## 📊 מדדים וניטור
- Product: זמן עד אישור ראשון (TTA), שיעור מסירה, שיעור אישור, שיעור הצלחה
- Tech: שיעור כשלים לפי ערוץ, זמן תגובה API, שימוש בתבניות
- ניטור: health checks, התראות על חריגה מ‑SLA, dashboard בסיסי

---

## 🧭 Runbook קצר
- נפילת Twilio: מעבר לערוץ חלופי (Email/SMS) ומעבר ל"slow mode"
- Rate limit ב‑Google: חזרה עם backoff ומעבר ל‑Overpass/Cache
- מצב תחזוקה: הפעלת DRY_RUN=true, לוגים מלאים בלבד
- שחזור נתונים: שמירת sources ו‑organization_sources לאיתור מקור רשומות

---

## 💰 עלויות (הערכה)
| רכיב | עלות חודשית | הערות |
|------|-------------|--------|
| Google Places Details | $20–50 | תלוי בשדות ובנפח |
| SerpAPI | ~$80 | אלטרנטיבה פשוטה למפות |
| Twilio (SMS/WhatsApp) | $100–200 | להתראות |
| שרת + DB | $20–30 | Render/Cloud/Postgres |
| Overpass/OSM | $0 | חינמי (rate limits) |

---

## 📦 קבצים נלווים בריפו
- docs/ANIMAL_RESCUE_IMPROVEMENT.md – מסמך זה
- docs/seed/organizations_seed.csv – תבנית זרעים + דוגמאות

---

## 📝 צעדים הבאים (לביצוע)
1. יצירת חשבונות API (Google, Twilio, SerpAPI) והגדרת ENV
2. יבוא seed ראשוני מ‑CSV, הפעלת מנגנון נרמול ואימות
3. פריסת מערכת התראות ל‑WhatsApp+SMS, תבניות מאושרות
4. Dashboard מדדים בסיסי + ניטור בריאות

---

נכתב לתרומה לקהילה – ספטמבר 2025.
