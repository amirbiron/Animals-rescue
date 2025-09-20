# 🔧 בעיות טכניות ופתרונות – Animal Rescue Bot

## 🚨 הבעיה המרכזית: חוסר בפרטי התקשרות

### מה קורה כרגע בקוד?
1. **הבוט מחפש ארגונים** דרך `app/workers/jobs.py` בפונקציות:
   - `_find_organizations_by_location()` – חיפוש לפי מרחק
   - `_find_organizations_by_type()` – חיפוש לפי סוג חיה

2. **הבעיה**: הארגונים במסד הנתונים **ריקים מפרטי קשר**:
   - אין טלפונים (`primary_phone`, `emergency_phone`)
   - אין מיילים (`email`)
   - אין Telegram Chat IDs (`telegram_chat_id`)

3. **התוצאה**: כשהבוט מנסה לשלוח התראה ב-`send_organization_alert()`:
   ```python
   # שורות 516-530 ב-app/workers/jobs.py
   if channel == "telegram" and organization.telegram_chat_id:
       recipient = organization.telegram_chat_id
   elif channel == "email" and organization.email:
       recipient = organization.email
   elif channel == "sms" and organization.primary_phone:
       recipient = organization.primary_phone
   
   if not recipient:
       return {"status": "failed", "message": f"No {channel} contact configured"}
   ```
   **הבוט נכשל כי אין פרטי קשר!**

---

## 🛠️ פתרונות טכניים מיידיים

### פתרון 1: הוספת Place Details API
הקוד הקיים ב-`app/services/google.py` משתמש רק ב-**Text Search API** שלא מחזיר פרטי קשר.

**מה צריך להוסיף:**
```python
async def get_place_details(self, place_id: str) -> Dict[str, Any]:
    """
    שליפת פרטים מלאים של מקום כולל טלפון ואתר.
    
    עלות: $0.017 לקריאה (יקר יותר מ-Text Search)
    """
    url = f"{self.places_base_url}/details/json"
    params = {
        "place_id": place_id,
        "key": self.places_api_key,
        "fields": "formatted_phone_number,international_phone_number,website,opening_hours",
        "language": "he"
    }
    
    response = await self.client.get(url, params=params)
    data = response.json()
    
    return {
        "phone": data.get("result", {}).get("formatted_phone_number"),
        "international_phone": data.get("result", {}).get("international_phone_number"),
        "website": data.get("result", {}).get("website"),
        "hours": data.get("result", {}).get("opening_hours")
    }
```

### פתרון 2: סקריפט לאיסוף נתונים
יצירת סקריפט נפרד לאיסוף ארגונים:

```python
# scripts/collect_organizations.py
import asyncio
from app.services.google import GoogleService
from app.models.database import Organization, async_session_maker

async def collect_veterinary_data():
    """אוסף נתונים על וטרינרים בערים מרכזיות"""
    
    cities = [
        "תל אביב", "ירושלים", "חיפה", "באר שבע", 
        "פתח תקווה", "ראשון לציון", "נתניה", "אשדוד"
    ]
    
    async with GoogleService() as google:
        for city in cities:
            # חיפוש וטרינרים בעיר
            places = await google.search_places(
                query=f"וטרינר {city}",
                place_type="veterinary_care"
            )
            
            for place in places:
                # שליפת פרטים מלאים (כולל טלפון)
                details = await google.get_place_details(place["place_id"])
                
                # שמירה במסד נתונים
                async with async_session_maker() as session:
                    org = Organization(
                        name=place["name"],
                        address=place["address"],
                        latitude=place["latitude"],
                        longitude=place["longitude"],
                        primary_phone=details.get("phone"),
                        website=details.get("website"),
                        google_place_id=place["place_id"],
                        organization_type="vet_clinic",
                        is_active=True
                    )
                    session.add(org)
                    await session.commit()
                
                print(f"נוסף: {place['name']} - {details.get('phone', 'אין טלפון')}")
            
            # המתנה בין ערים (rate limiting)
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(collect_veterinary_data())
```

### פתרון 3: שימוש ב-SerpAPI (חלופה פשוטה)
```python
# app/services/serpapi.py
import serpapi

class SerpAPIService:
    def __init__(self):
        self.client = serpapi.Client(api_key=settings.SERPAPI_KEY)
    
    def search_local(self, query: str, location: str):
        """חיפוש מקומי עם פרטי קשר מלאים"""
        results = self.client.search({
            "engine": "google_maps",
            "q": query,
            "ll": f"@{location},14z",
            "type": "search"
        })
        
        organizations = []
        for place in results.get("local_results", []):
            organizations.append({
                "name": place.get("title"),
                "address": place.get("address"),
                "phone": place.get("phone"),  # מגיע ישירות!
                "website": place.get("website"),
                "hours": place.get("hours"),
                "rating": place.get("rating")
            })
        
        return organizations
```

### פתרון 4: Web Scraping (חינמי אבל מורכב)
```python
# scripts/scrape_vets.py
import httpx
from bs4 import BeautifulSoup

async def scrape_veterinary_association():
    """גריפת נתונים מאתר ההתאחדות הווטרינרית"""
    url = "https://www.ivma.org.il/vets-list"  # דוגמה
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        vets = []
        for vet_card in soup.find_all("div", class_="vet-info"):
            vets.append({
                "name": vet_card.find("h3").text,
                "phone": vet_card.find("span", class_="phone").text,
                "address": vet_card.find("p", class_="address").text,
                "email": vet_card.find("a", class_="email")["href"].replace("mailto:", "")
            })
        
        return vets
```

---

## 📝 סדר עדיפויות לתיקון

### שלב 1: איסוף ידני מיידי (יום אחד)
```sql
-- הכנסת 10 ארגונים ידנית למסד נתונים
INSERT INTO organizations (
    name, primary_phone, email, address, city,
    latitude, longitude, organization_type, is_24_7, is_active
) VALUES 
    ('מרפאה וטרינרית תל אביב', '03-1234567', 'info@vet-tlv.co.il', 
     'רחוב דיזנגוף 100', 'תל אביב', 32.0853, 34.7818, 'vet_clinic', true, true),
    ('צער בעלי חיים ישראל', '03-7654321', 'help@spca.org.il',
     'הרצל 159', 'תל אביב', 32.0623, 34.7701, 'rescue_org', false, true);
-- וכו'...
```

### שלב 2: הוספת Place Details API (3 ימים)
1. עדכון `GoogleService` עם `get_place_details()`
2. עדכון `process_new_report()` לקרוא גם ל-Details API
3. הוספת caching אגרסיבי (שמירה ל-30 יום)

### שלב 3: סקריפט איסוף אוטומטי (שבוע)
1. כתיבת `scripts/collect_organizations.py`
2. הרצה על 50 ערים מרכזיות
3. איסוף ~500 ארגונים עם פרטי קשר

### שלב 4: אינטגרציה עם APIs חיצוניים (2 שבועות)
1. SerpAPI להעשרת נתונים
2. Twilio לאימות טלפונים
3. SendGrid לאימות מיילים

---

## 🎯 בדיקות נדרשות

### בדיקת פרטי קשר
```python
# tests/test_contact_data.py
async def test_organization_has_contact():
    """וידוא שלכל ארגון יש לפחות דרך קשר אחת"""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Organization).where(
                and_(
                    Organization.is_active == True,
                    or_(
                        Organization.primary_phone.isnot(None),
                        Organization.email.isnot(None),
                        Organization.telegram_chat_id.isnot(None)
                    )
                )
            )
        )
        orgs_with_contact = result.scalars().all()
        
        total = await session.execute(
            select(func.count()).select_from(Organization)
            .where(Organization.is_active == True)
        )
        
        coverage = len(orgs_with_contact) / total.scalar() * 100
        assert coverage >= 80, f"רק {coverage:.1f}% מהארגונים עם פרטי קשר"
```

### בדיקת שליחת התראות
```python
async def test_alert_delivery():
    """בדיקה שהתראות נשלחות בהצלחה"""
    # יצירת דיווח מדומה
    report = create_test_report()
    
    # חיפוש ארגונים
    orgs = await find_organizations_by_location(
        report.latitude, report.longitude, report.urgency_level
    )
    
    assert len(orgs) > 0, "לא נמצאו ארגונים באזור"
    
    # שליחת התראה
    for org in orgs[:3]:
        result = await send_organization_alert(
            str(report.id), str(org.id), "telegram"
        )
        assert result["status"] != "failed", f"נכשלה שליחה ל-{org.name}"
```

---

## 💡 טיפים חשובים

1. **התחילו קטן**: 10 ארגונים ידניים מספיקים ל-POC
2. **העדיפו איכות**: ארגון אחד עם פרטי קשר מלאים עדיף על 100 בלי
3. **בקשו עזרה**: פנו לעמותות – הן ישמחו לעזור
4. **תעדו הכל**: כל ארגון שנוסף, כל API שנבדק
5. **בדקו פעמיים**: טלפונים ומיילים משתנים – צריך תחזוקה

---

*מסמך זה נכתב כדי לעזור למפתחים להבין ולתקן את הבעיה המרכזית של הבוט.*