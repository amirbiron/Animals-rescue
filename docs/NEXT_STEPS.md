# 🚀 הצעדים הבאים – מדריך למפתחים

## למי שלוקח את הפרויקט הלאה

### 📌 סדר עדיפויות מיידי

#### 1️⃣ שבוע ראשון: הפעלה בסיסית
- [ ] הרצת הבוט עם 10-20 ארגונים ידניים
- [ ] בדיקה שהתראות נשלחות (לפחות במייל)
- [ ] תיקון באגים קריטיים שיתגלו
- [ ] יצירת קבוצת טלגרם לבטא טסטרים

#### 2️⃣ שבוע שני: איסוף נתונים
- [ ] הרשמה ל-Google Places API
- [ ] הרצת `collect_organizations.py` על 10 ערים מרכזיות
- [ ] איסוף לפחות 100 ארגונים עם טלפונים
- [ ] אימות ידני של 20 הארגונים החשובים ביותר

#### 3️⃣ שבוע שלישי-רביעי: שיפורים
- [ ] הוספת Place Details API לקוד
- [ ] מימוש מערכת הסלמה (אם ארגון לא עונה → הבא בתור)
- [ ] הוספת דשבורד פשוט לסטטיסטיקות
- [ ] שילוב עם WhatsApp Business API

---

## 🛠️ תיקונים טכניים נדרשים

### תיקון 1: הוספת get_place_details ל-GoogleService
```python
# app/services/google.py - להוסיף פונקציה חדשה
async def get_place_details(self, place_id: str) -> Dict[str, Any]:
    """שליפת פרטי מקום מלאים כולל טלפון"""
    url = f"{self.places_base_url}/details/json"
    params = {
        "place_id": place_id,
        "key": self.places_api_key,
        "fields": "formatted_phone_number,website,opening_hours",
        "language": "he"
    }
    response = await self.client.get(url, params=params)
    data = response.json()
    return data.get("result", {})
```

### תיקון 2: עדכון process_new_report
```python
# app/workers/jobs.py - לעדכן את _find_organizations_by_location
# להוסיף אחרי שורה 302:
for org in candidates:
    # אם אין טלפון, נסה לשלוף מ-Google
    if not org.primary_phone and org.google_place_id:
        details = await google_service.get_place_details(org.google_place_id)
        if details.get("formatted_phone_number"):
            org.primary_phone = details["formatted_phone_number"]
            # שמור במסד נתונים לפעם הבאה
            await session.execute(
                update(Organization)
                .where(Organization.id == org.id)
                .values(primary_phone=details["formatted_phone_number"])
            )
```

### תיקון 3: הוספת fallback לשליחת התראות
```python
# app/workers/jobs.py - שורה 516
# במקום להיכשל, נסה ערוצים אחרים:
channels_priority = ["telegram", "whatsapp", "sms", "email"]
for channel in channels_priority:
    recipient = None
    if channel == "telegram" and organization.telegram_chat_id:
        recipient = organization.telegram_chat_id
    elif channel == "whatsapp" and organization.primary_phone:
        recipient = organization.primary_phone
    elif channel == "sms" and organization.primary_phone:
        recipient = organization.primary_phone
    elif channel == "email" and organization.email:
        recipient = organization.email
    
    if recipient:
        # נמצא ערוץ זמין - שלח התראה
        break
else:
    # אין אף ערוץ זמין
    logger.error(f"No contact method for {organization.name}")
    return {"status": "failed", "message": "No contact configured"}
```

---

## 📊 מדדי הצלחה לבדיקה

### אחרי שבוע
- [ ] לפחות דיווח אחד עבר מהתחלה לסוף
- [ ] לפחות ארגון אחד קיבל התראה
- [ ] הבוט עובד ללא קריסות 24 שעות

### אחרי חודש
- [ ] 10+ דיווחים מוצלחים
- [ ] 50+ ארגונים עם פרטי קשר
- [ ] זמן תגובה ממוצע < 10 דקות
- [ ] 3+ ערוצי התראה פעילים

### אחרי 3 חודשים
- [ ] 100+ דיווחים
- [ ] 200+ ארגונים
- [ ] כיסוי של 20+ ערים
- [ ] שיתוף פעולה עם לפחות עמותה אחת גדולה

---

## 🤝 שיתופי פעולה מומלצים

### ארגונים לפנייה ראשונית
1. **אגודת צער בעלי חיים** - הכי גדולה וותיקה
2. **תנו לחיות לחיות** - פעילים מאוד ופתוחים לטכנולוגיה
3. **SOS חיות** - מתמחים בחילוצים דחופים
4. **Let the Animals Live** - קהילה גדולה באנגלית

### מה להציע להם
- גישה חינמית למערכת
- דשבורד ייעודי לארגון
- סטטיסטיקות על אזורי פעילות
- אפשרות לנהל מתנדבים

### מה לבקש מהם
- רשימת סניפים ומתנדבים
- פרטי קשר לחירום
- משוב על הממשק
- עזרה בהפצה

---

## 💡 רעיונות לעתיד

### פיצ'רים מתקדמים
- **AI לזיהוי תמונות** - זיהוי אוטומטי של סוג החיה ומצבה
- **מפת חום** - הצגת אזורים עם הרבה דיווחים
- **מערכת מתנדבים** - חיבור מתנדבים קרובים לדיווחים
- **אפליקציה נייטיב** - לא רק בוט טלגרם

### אינטגרציות
- **Waze** - ניווט ישיר לנקודת החילוץ
- **מוקד 106** - העברת דיווחים לעירייה
- **רשתות חברתיות** - פרסום אוטומטי של חילוצים מוצלחים

### מודל עסקי (אופציונלי)
- **מנוי פרימיום לארגונים** - דשבורד מתקדם, API, סטטיסטיקות
- **תרומות** - אפשרות לתרום דרך הבוט לארגון שטיפל
- **מימון ממשלתי** - הצעה למשרד החקלאות/איכות הסביבה

---

## 📞 צור קשר

אם אתה לוקח את הפרויקט קדימה:
1. פתח Issue ב-GitHub עם התקדמות
2. שתף את הקהילה בשיפורים
3. בקש עזרה כשצריך - הקהילה כאן לעזור!

---

## 🙏 תודה מיוחדת

תודה שאתה לוקח את הפרויקט קדימה!  
כל חיה שתציל בזכות הבוט הזה - זו הצלחה משותפת של כולנו.

**ביחד נציל חיים! 🐾❤️**