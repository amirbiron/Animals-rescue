# 🛠️ מדריך יישום טכני – בניית בסיס נתונים ארגונים

## 🎯 מטרה
מדריך מעשי לבניית בסיס נתונים של ארגוני חילוץ עם פרטי קשר מלאים.

---

## 📋 דרישות מוקדמות

### API Keys נדרשים
# Google APIs
GOOGLE_PLACES_API_KEY=your_key_here
GOOGLE_GEOCODING_API_KEY=your_key_here  # אופציונלי

# SerpAPI (אלטרנטיבה)
SERPAPI_KEY=your_key_here

# Twilio (לאימות טלפונים)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
### חבילות Python נוספות
pip install googlemaps serpapi twilio phonenumbers
---

## 🏗️ שלב 1: הגדרת מודל נתונים

### הרחבת מודל Organization
# app/models/database.py - הוספה למודל הקיים

from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, Float
from sqlalchemy.dialects.postgresql import ARRAY

class Organization(Base):
    __tablename__ = "organizations"
    
    # שדות קיימים...
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    
    # שדות חדשים נדרשים
    phone = Column(String(20))  # טלפון ראשי
    phone_emergency = Column(String(20))  # טלפון חירום
    whatsapp = Column(String(20))  # WhatsApp
    website = Column(String(500))
    
    # מיקום מדויק
    latitude = Column(Float)
    longitude = Column(Float)
    address_full = Column(String(500))
    city = Column(String(100))
    postal_code = Column(String(10))
    
    # מטא-דטה
    google_place_id = Column(String(200), unique=True)
    google_rating = Column(Float)
    google_reviews_count = Column(Integer)
    
    # יכולות ושירותים
    services = Column(ARRAY(String))  # ['emergency', 'surgery', 'shelter', 'rescue']
    animal_types = Column(ARRAY(String))  # ['dogs', 'cats', 'wildlife', 'farm']
    operating_hours = Column(JSON)  # {"monday": "08:00-18:00", "emergency": "24/7"}
    
    # סטטוס ואימות
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    last_contacted = Column(DateTime)
    response_rate = Column(Float, default=0.0)  # אחוז תגובה
    
    # אזור כיסוי
    coverage_radius_km = Column(Integer, default=20)
    coverage_cities = Column(ARRAY(String))
---

## 🔍 שלב 2: איסוף נתונים עם Google Places API

### סקריפט איסוף בסיסי
`python
# scripts/collect_organizations.py

import googlemaps
import asyncio
from typing import List, Dict
from app.core.config import settings
from app.models.database import Organization

class OrganizationCollector:
    initit__(self):
        self.gmaps = googlemaps.Client(key=settings.GOOGLE_PLACES_API_KEY)
        
    def search_places(self, query: str, location: str, radius: int = 50000) -> List[Dict]:
        """חיפוש מקומות בGoogle Places"""
        try:
            # חיפוש ראשוני
            places_result = self.gmaps.places_nearby(
                location=location,  # "31.0461,34.8516" (תל אביב)
                radius=radius,
                keyword=query,
                type='veterinary_care'
            )
            
            detailed_places = []
            for place in places_result.get('results', []):
                # קבלת פרטים מלאים
                place_details = self.gmaps.place(
                    place_id=place['place_id'],
                    fields=[
                        'name', 'formatted_address', 'international_phone_number',
                        'website', 'rating', 'user_ratings_total', 'geometry',
                        'opening_hours', 'types', 'place_id'
                    ]
                )
                detailed_places.append(place_details['result'])
                
            return detailed_places
            
        except Exception as e:
            print(f"שגיאה בחיפוש: {e}")
            return []
    
    def search_multiple_locations(self) -> List[Dict]:
        """חיפוש במספר ערים"""
cities = [
            ("31.0461,34.8516", "תל אביב"),
            ("32.0853,34.7818", "חיפה"), 
            ("31.2518,34.7915", "באר שבע"),
            ("32.7940,35.0179", "צפת"),
            ("31.7683,35.2137", "ירושלים")
        ]
        
        queries = [
            "וטרינר",
            "מרפאה וטרינרית", 
            "animal shelter",
            "מקלט בעלי חיים",
            "חילוץ בעלי חיים"
        ]
        
        all_places = []
        for location, city_name in cities:
            for query in queries:
                print(f"מחפש '{query}' ב{city_name}")
                places = self.search_places(query, location)
                all_places.extend(places)
                
        return self.deduplicate_places(all_places)
    
    def deduplicate_places(self, places: List[Dict]) -> List[Dict]:
        """הסרת כפילויות לפי place_id"""
        seen_ids = set()
        unique_places = []
        
        for place in places:
            place_id = place.get('place_id')
            if place_id and place_id not in seen_ids:
                seen_ids.add(place_id)
                unique_places.append(place)
                
        return unique_places

# שימוש
async def collect_and_save():
    collector = OrganizationCollector()
    places = collector.search_multiple_locations()
    
    print(f"נמצאו {len(places)} מקומות")
    
    # שמירה לDB
    for place in places:
        org = Organization(
            name=place.get('name'),
            phone=place.get('international_phone_number'),
            website=place.get('website'),
            address_full=place.get('formatted_address'),
            google_place_id=place.get('place_id'),
            google_rating=place.get('rating'),
            google_reviews_count=place.get('user_ratings_total'),
            latitude=place['geometry']['location']['lat'],
            longitude=place['geometry']['location']['lng'],
            is_verified=False
        )
        # שמירה ל-DB...

if name == "main":
    asyncio.run(collect_and_save())

---

## 📞 שלב 3: השלמת פרטי קשר עם SerpAPI

python
# scripts/enhance_contacts.py

import requests
from serpapi import GoogleSearch

class ContactEnhancer:
    def init(self, serpapi_key: str):
        self.api_key = serpapi_key
        
    def get_contact_details(self, business_name: str, city: str) -> Dict:
        """חיפוש פרטי קשר בGoogle Maps דרך SerpAPI"""
        params = {
            "engine": "google_maps",
            "q": f"{business_name} {city}",
            "api_key": self.api_key
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if 'local_results' in results and results['local_results']:
            place = results['local_results'][0]
            return {
                'phone': place.get('phone'),
                'website': place.get('website'),
                'hours': place.get('hours'),
                'rating': place.get('rating'),
                'reviews': place.get('reviews'),
                'address': place.get('address')
            }
        
        return {}
    
    def enhance_organization(self, org: Organization) -> Organization:
        """השלמת פרטים לארגון קיים"""
        if not org.phone or not org.website:
            details = self.get_contact_details(org.name, org.city or "ישראל")
            
            if details.get('phone') and not org.phone:
                org.phone = details['phone']
            if details.get('website') and not org.website:
                org.website = details['website']
                
        return org

---

## ✅ שלב 4: אימות ונקיון נתונים

python
# scripts/validate_data.py

import phonenumbers
from phonenumbers import geocoder, carrier
import requests
from urllib.parse import urlparse
class DataValidator:
    def validate_phone(self, phone: str, country: str = "IL") -> Dict:
        """אימות מספר טלפון"""
        try:
            parsed = phonenumbers.parse(phone, country)
            is_valid = phonenumbers.is_valid_number(parsed)
            
            return {
                'is_valid': is_valid,
                'formatted': phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                'location': geocoder.description_for_number(parsed, 'he'),
                'carrier': carrier.name_for_number(parsed, 'he')
            }
        except:
            return {'is_valid': False}
    
    def validate_website(self, url: str) -> Dict:
        """בדיקת זמינות אתר"""
        try:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                
            response = requests.head(url, timeout=10, allow_redirects=True)
            return {
                'is_accessible': response.status_code < 400,
                'status_code': response.status_code,
                'final_url': response.url
            }
        except:
            return {'is_accessible': False}
    
    def validate_coordinates(self, lat: float, lng: float) -> bool:
        """בדיקה שהקואורדינטות בישראל"""
        # גבולות ישראל בקירוב
        return (29.5 <= lat <= 33.5) and (34.0 <= lng <= 36.0)
    
    async def validate_organization(self, org: Organization) -> Dict:
        """אימות מקיף של ארגון"""
        results = {
            'phone_valid': False,
            'website_accessible': False,
            'coordinates_valid': False,
            'completeness_score': 0
        }
        
        # אימות טלפון
        if org.phone:
            phone_result = self.validate_phone(org.phone)
            results['phone_valid'] = phone_result['is_valid']
            if phone_result['is_valid']:
                org.phone = phone_result['formatted']
        
        # אימות אתר
        if org.website:
            website_result = self.validate_website(org.website)
            results['website_accessible'] = website_result['is_accessible']
        
        # אימות קואורדינטות
        if org.latitude and org.longitude:
            results['coordinates_valid'] = self.validate_coordinates(
                org.latitude, org.longitude
            )
        
        # ציון שלמות
        completeness_fields = [
            org.name, org.phone, org.email, org.website, 
            org.address_full, org.latitude, org.longitude
        ]
        results['completeness_score'] = sum(1 for field in completeness_fields if field) / len(completeness_fields)
        
        return results

---

## 🤖 שלב 5: אוטומציה מלאה

python
# scripts/automated_collection.py

import asyncio
from datetime import datetime, timedelta
from app.workers.jobs import schedule_job

class AutomatedCollector:
    def init(self):
        self.collector = OrganizationCollector()
        self.enhancer = ContactEnhancer(settings.SERPAPI_KEY)
        self.validator = DataValidator()
    
    async def daily_collection_job(self):
        """משימה יומית לאיסוף ועדכון נתונים"""
        print("מתחיל איסוף יומי...")
        
        # 1. איסוף מקומות חדשים
        new_places = self.collector.search_multiple_locations()
        
        # 2. השלמת פרטי קשר
        for place in new_places:
            enhanced = self.enhancer.get_contact_details(
                place.get('name', ''), 
                place.get('city', '')
            )
            place.update(enhanced)
        
        # 3. אימות ושמירה
        saved_count = 0
        for place in new_places:
            org = Organization(**self.map_place_to_org(place))
            validation = await self.validator.validate_organization(org)
if validation['completeness_score'] > 0.6:  # רק ארגונים עם מידע מספק
                # שמירה לDB
                saved_count += 1
        
        print(f"נשמרו {saved_count} ארגונים חדשים")
        
        # 4. עדכון ארגונים קיימים
        await self.update_existing_organizations()
    
    async def update_existing_organizations(self):
        """עדכון ארגונים קיימים שלא עודכנו זמן רב"""
        # ארגונים שלא עודכנו בשבוע האחרון
        old_orgs = await Organization.filter(
            last_updated__lt=datetime.now() - timedelta(days=7)
        ).limit(50)
        
        for org in old_orgs:
            # בדיקת זמינות
            validation = await self.validator.validate_organization(org)
            
            if not validation['phone_valid'] or not validation['website_accessible']:
                # ניסיון לעדכן פרטים
                enhanced = self.enhancer.get_contact_details(org.name, org.city)
                if enhanced:
                    org.phone = enhanced.get('phone', org.phone)
                    org.website = enhanced.get('website', org.website)
                    await org.save()
    
    def map_place_to_org(self, place: Dict) -> Dict:
        """המרת נתוני Google Places למודל Organization"""
        return {
            'name': place.get('name'),
            'phone': place.get('phone'),
            'website': place.get('website'),
            'address_full': place.get('address'),
            'google_place_id': place.get('place_id'),
            'google_rating': place.get('rating'),
            'latitude': place.get('geometry', {}).get('location', {}).get('lat'),
            'longitude': place.get('geometry', {}).get('location', {}).get('lng'),
            'is_verified': False,
            'services': self.extract_services(place),
            'animal_types': self.extract_animal_types(place)
        }
    
    def extract_services(self, place: Dict) -> List[str]:
        """זיהוי שירותים לפי סוג המקום"""
        types = place.get('types', [])
        services = []
        
        if 'veterinary_care' in types:
            services.extend(['medical', 'emergency'])
        if 'pet_store' in types:
            services.append('supplies')
        if any('hospital' in t for t in types):
            services.extend(['surgery', '24/7'])
            
        return services
    
    def extract_animal_types(self, place: Dict) -> List[str]:
        """זיהוי סוגי בעלי חיים לפי שם המקום"""
        name = place.get('name', '').lower()
        types = []
        
        if any(word in name for word in ['כלב', 'dog']):
            types.append('dogs')
        if any(word in name for word in ['חתול', 'cat']):
            types.append('cats')
        if any(word in name for word in ['חיות בר', 'wildlife']):
            types.append('wildlife')
        if not types:  # ברירת מחדל
            types = ['dogs', 'cats']
            
        return types

# הגדרת משימה אוטומטית
def setup_automated_collection():
    """הגדרת איסוף אוטומטי יומי"""
    collector = AutomatedCollector()
    
    # הרצה יומית בשעה 02:00
    schedule_job(
        func=collector.daily_collection_job,
        schedule_type='cron',
        hour=2,
        minute=0
    )
    
    print("הוגדר איסוף אוטומטי יומי בשעה 02:00")

---

## 📊 שלב 6: ניטור ודשבורד

python
# app/api/v1/organizations_stats.py

from fastapi import APIRouter, Depends
from app.models.database import Organization

router = APIRouter(prefix="/organizations", tags=["organizations"])

@router.get("/stats")
async def get_organizations_stats():
    """סטטיסטיקות בסיס נתונים הארגונים"""
    total = await Organization.count()
    verified = await Organization.filter(is_verified=True).count()
    with_phone = await Organization.filter(phone__isnull=False).count()
    with_email = await Organization.filter(email__isnull=False).count()
# פילוח לפי שירותים
    services_stats = {}
    for service in ['emergency', 'surgery', 'shelter', 'rescue']:
        count = await Organization.filter(services__contains=[service]).count()
        services_stats[service] = count
    
    # פילוח גיאוגרפי
    cities = await Organization.values_list('city', flat=True).distinct()
    geographic_stats = {}
    for city in cities:
        if city:
            count = await Organization.filter(city=city).count()
            geographic_stats[city] = count
    
    return {
        'total_organizations': total,
        'verified_organizations': verified,
        'completion_rates': {
            'phone': (with_phone / total) * 100 if total > 0 else 0,
            'email': (with_email / total) * 100 if total > 0 else 0,
            'verified': (verified / total) * 100 if total > 0 else 0
        },
        'services_distribution': services_stats,
        'geographic_distribution': geographic_stats
    }

@router.get("/quality-report")
async def get_quality_report():
    """דוח איכות נתונים"""
    # ארגונים עם נתונים חסרים
    incomplete_orgs = await Organization.filter(
        models.Q(phone__isnull=True) | 
        models.Q(email__isnull=True) |
        models.Q(latitude__isnull=True)
    ).count()
    
    # ארגונים שלא אומתו
    unverified = await Organization.filter(is_verified=False).count()
    
    # ארגונים ישנים (לא עודכנו בחודש)
    month_ago = datetime.now() - timedelta(days=30)
    stale_orgs = await Organization.filter(
        last_updated__lt=month_ago
    ).count()
    
    return {
        'data_quality': {
            'incomplete_organizations': incomplete_orgs,
            'unverified_organizations': unverified,
            'stale_organizations': stale_orgs
        },
        'recommendations': [
            f"יש לאמת {unverified} ארגונים",
            f"יש להשלים נתונים עבור {incomplete_orgs} ארגונים",
            f"יש לעדכן {stale_orgs} ארגונים ישנים"
        ]
    }

---

## 🚀 הפעלה מעשית

### הרצת סקריפט איסוף חד-פעמי
bash
cd /workspace
python scripts/collect_organizations.py

### הגדרת איסוף אוטומטי
bash
# הוספה ל-worker startup
python -c "
from scripts.automated_collection import setup_automated_collection
setup_automated_collection()
"

### בדיקת תוצאות
bash
# API endpoint לסטטיסטיקות
curl http://localhost:8000/api/v1/organizations/stats

# בדיקת איכות נתונים
curl http://localhost:8000/api/v1/organizations/quality-report
`

---

## 📈 מטרות ביצועים

### שבוע ראשון
- [ ] 50+ ארגונים עם פרטי קשר בסיסיים
- [ ] 80%+ מהטלפונים תקינים
- [ ] כיסוי 5 ערים מרכזיות

### חודש ראשון  
- [ ] 200+ ארגונים מאומתים
- [ ] 90%+ שלמות נתונים
- [ ] כיסוי ארצי בסיסי

### 3 חודשים
- [ ] 500+ ארגונים פעילים
- [ ] אוטומציה מלאה
- [ ] שיעור תגובה >70%

---

*המדריך הזה מספק בסיס מוצק לבניית מערכת איסוף נתונים מתקדמת ואמינה.*
