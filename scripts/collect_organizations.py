#!/usr/bin/env python3
"""
סקריפט לאיסוף ארגונים עם פרטי התקשרות
==========================================

סקריפט זה אוסף נתונים על ארגונים (וטרינרים, מקלטים, עמותות) 
מ-APIs שונים ושומר אותם במסד הנתונים עם פרטי קשר מלאים.

שימוש:
    python scripts/collect_organizations.py --source google --cities "תל אביב,ירושלים"
    python scripts/collect_organizations.py --source manual --file data/organizations.csv
"""

import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import argparse

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

import httpx
import structlog
from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError

from app.models.database import (
    Organization, OrganizationType, async_session_maker
)
from app.services.google import GoogleService
from app.services.geocoding import GeocodingService
from app.core.config import settings

logger = structlog.get_logger(__name__)


# ============================================================================
# Google Places Collector
# ============================================================================

class GooglePlacesCollector:
    """אוסף נתונים מ-Google Places API כולל Place Details"""
    
    def __init__(self):
        self.google_service = GoogleService()
        self.geocoding_service = GeocodingService()
        
    async def collect_from_city(
        self, city: str, 
        search_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        אוסף ארגונים מעיר ספציפית
        
        Args:
            city: שם העיר
            search_types: סוגי חיפוש (veterinary_care, animal_shelter, pet_store)
        """
        if not search_types:
            search_types = [
                "veterinary_care",
                "animal shelter",
                "emergency vet",
                "animal hospital"
            ]
        
        organizations = []
        
        async with self.google_service:
            for search_type in search_types:
                query = f"{search_type} {city}"
                logger.info(f"מחפש: {query}")
                
                try:
                    # חיפוש ראשוני
                    places = await self.google_service.search_places(
                        query=query,
                        place_type="veterinary_care" if "vet" in search_type else None,
                        language="he"
                    )
                    
                    for place in places:
                        # שליפת פרטים מלאים (כולל טלפון)
                        details = await self._get_place_details(
                            place.get("place_id")
                        )
                        
                        if details:
                            org_data = self._merge_place_data(place, details)
                            organizations.append(org_data)
                            
                            logger.info(
                                f"נמצא: {org_data['name']} - "
                                f"טלפון: {org_data.get('primary_phone', 'אין')}"
                            )
                        
                        # המתנה בין קריאות (rate limiting)
                        await asyncio.sleep(0.5)
                        
                except Exception as e:
                    logger.error(f"שגיאה בחיפוש {query}: {e}")
                    continue
                
                # המתנה בין סוגי חיפוש
                await asyncio.sleep(2)
        
        return organizations
    
    async def _get_place_details(self, place_id: str) -> Optional[Dict]:
        """שליפת פרטי מקום מלאים כולל טלפון ואתר"""
        if not place_id:
            return None
            
        try:
            # הוספת פונקציה ל-GoogleService (צריך להוסיף לקוד)
            url = f"{self.google_service.places_base_url}/details/json"
            params = {
                "place_id": place_id,
                "key": self.google_service.places_api_key,
                "fields": (
                    "formatted_phone_number,international_phone_number,"
                    "website,opening_hours,business_status,url"
                ),
                "language": "he"
            }
            
            response = await self.google_service.client.get(url, params=params)
            data = response.json()
            
            if data.get("status") == "OK":
                return data.get("result", {})
            
        except Exception as e:
            logger.error(f"שגיאה בשליפת פרטי {place_id}: {e}")
        
        return None
    
    def _merge_place_data(
        self, basic_data: Dict, details: Dict
    ) -> Dict[str, Any]:
        """מיזוג נתונים בסיסיים עם פרטים מלאים"""
        
        # קביעת סוג הארגון
        org_type = self._determine_org_type(
            basic_data.get("types", []),
            basic_data.get("name", "")
        )
        
        # עיבוד שעות פעילות
        hours = None
        if details.get("opening_hours"):
            hours = {
                "weekday_text": details["opening_hours"].get("weekday_text", []),
                "periods": details["opening_hours"].get("periods", [])
            }
        
        return {
            "name": basic_data.get("name"),
            "name_en": basic_data.get("name"),  # לשמור גם באנגלית
            "address": basic_data.get("formatted_address"),
            "latitude": basic_data.get("geometry", {}).get("location", {}).get("lat"),
            "longitude": basic_data.get("geometry", {}).get("location", {}).get("lng"),
            "primary_phone": details.get("formatted_phone_number"),
            "international_phone": details.get("international_phone_number"),
            "website": details.get("website"),
            "google_place_id": basic_data.get("place_id"),
            "google_maps_url": details.get("url"),
            "organization_type": org_type,
            "is_24_7": self._check_if_24_7(hours),
            "operating_hours": hours,
            "rating": basic_data.get("rating"),
            "total_ratings": basic_data.get("user_ratings_total"),
            "business_status": details.get("business_status", "OPERATIONAL"),
            "is_active": details.get("business_status") == "OPERATIONAL"
        }
    
    def _determine_org_type(self, types: List[str], name: str) -> str:
        """קביעת סוג הארגון לפי הנתונים"""
        name_lower = name.lower()
        
        if "veterinary_care" in types:
            if "emergency" in name_lower or "חירום" in name:
                return OrganizationType.EMERGENCY_VET.value
            elif "hospital" in name_lower or "בית חולים" in name:
                return OrganizationType.ANIMAL_HOSPITAL.value
            else:
                return OrganizationType.VET_CLINIC.value
        
        if any(t in types for t in ["animal_shelter", "pet_adoption"]):
            return OrganizationType.ANIMAL_SHELTER.value
        
        if "עמותה" in name or "אגודה" in name:
            return OrganizationType.RESCUE_ORG.value
        
        if "עירייה" in name or "מועצה" in name:
            return OrganizationType.GOVERNMENT.value
        
        return OrganizationType.VET_CLINIC.value  # ברירת מחדל
    
    def _check_if_24_7(self, hours: Optional[Dict]) -> bool:
        """בדיקה אם המקום פתוח 24/7"""
        if not hours or not hours.get("periods"):
            return False
        
        periods = hours["periods"]
        
        # אם יש רק period אחד עם open ללא close = 24/7
        if len(periods) == 1:
            period = periods[0]
            if "open" in period and "close" not in period:
                return True
        
        # בדיקה אם פתוח כל הזמן
        total_hours = 0
        for period in periods:
            if "open" in period and "close" in period:
                open_time = period["open"]
                close_time = period["close"]
                
                # חישוב שעות (פשוט - לא מדויק לגמרי)
                if open_time["day"] == close_time["day"]:
                    hours = int(close_time["time"][:2]) - int(open_time["time"][:2])
                    total_hours += hours
        
        # אם פתוח יותר מ-160 שעות בשבוע - כנראה 24/7
        return total_hours >= 160


# ============================================================================
# Manual CSV Collector
# ============================================================================

class ManualCSVCollector:
    """טוען ארגונים מקובץ CSV"""
    
    def __init__(self):
        self.geocoding_service = GeocodingService()
    
    async def collect_from_csv(self, file_path: str) -> List[Dict[str, Any]]:
        """
        טוען ארגונים מקובץ CSV
        
        פורמט CSV צפוי:
        name,phone,email,address,city,type,is_24_7,website
        """
        organizations = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Geocoding לכתובת
                lat, lon = None, None
                if row.get("address"):
                    coords = await self.geocoding_service.geocode_address(
                        f"{row['address']}, {row.get('city', 'ישראל')}"
                    )
                    if coords:
                        lat = coords["latitude"]
                        lon = coords["longitude"]
                
                org_data = {
                    "name": row["name"],
                    "primary_phone": row.get("phone"),
                    "email": row.get("email"),
                    "address": row.get("address"),
                    "city": row.get("city"),
                    "latitude": lat,
                    "longitude": lon,
                    "website": row.get("website"),
                    "organization_type": row.get("type", "vet_clinic"),
                    "is_24_7": row.get("is_24_7", "").lower() == "true",
                    "is_active": True,
                    "is_verified": True  # נתונים ידניים = מאומתים
                }
                
                organizations.append(org_data)
                logger.info(f"נטען: {org_data['name']}")
        
        return organizations


# ============================================================================
# Database Saver
# ============================================================================

class OrganizationSaver:
    """שומר ארגונים במסד הנתונים"""
    
    async def save_organizations(
        self, organizations: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        שומר רשימת ארגונים במסד הנתונים
        
        Returns:
            סטטיסטיקות: {added: X, updated: Y, failed: Z}
        """
        stats = {"added": 0, "updated": 0, "failed": 0}
        
        async with async_session_maker() as session:
            for org_data in organizations:
                try:
                    # בדיקה אם קיים (לפי Google Place ID או שם+עיר)
                    existing = await self._find_existing(session, org_data)
                    
                    if existing:
                        # עדכון ארגון קיים
                        for key, value in org_data.items():
                            if value is not None and hasattr(existing, key):
                                setattr(existing, key, value)
                        
                        stats["updated"] += 1
                        logger.info(f"עודכן: {org_data['name']}")
                    else:
                        # יצירת ארגון חדש
                        org = Organization(**org_data)
                        session.add(org)
                        
                        stats["added"] += 1
                        logger.info(f"נוסף: {org_data['name']}")
                    
                    await session.commit()
                    
                except IntegrityError as e:
                    await session.rollback()
                    stats["failed"] += 1
                    logger.error(f"שגיאת שלמות נתונים: {e}")
                    
                except Exception as e:
                    await session.rollback()
                    stats["failed"] += 1
                    logger.error(f"שגיאה בשמירת {org_data.get('name')}: {e}")
        
        return stats
    
    async def _find_existing(
        self, session, org_data: Dict
    ) -> Optional[Organization]:
        """מחפש ארגון קיים במסד הנתונים"""
        
        # חיפוש לפי Google Place ID
        if org_data.get("google_place_id"):
            result = await session.execute(
                select(Organization).where(
                    Organization.google_place_id == org_data["google_place_id"]
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing
        
        # חיפוש לפי שם ועיר
        if org_data.get("name") and org_data.get("city"):
            result = await session.execute(
                select(Organization).where(
                    and_(
                        Organization.name == org_data["name"],
                        Organization.city == org_data["city"]
                    )
                )
            )
            return result.scalar_one_or_none()
        
        return None


# ============================================================================
# Main Script
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="סקריפט לאיסוף ארגונים עם פרטי התקשרות"
    )
    
    parser.add_argument(
        "--source",
        choices=["google", "manual", "both"],
        default="google",
        help="מקור הנתונים"
    )
    
    parser.add_argument(
        "--cities",
        type=str,
        default="תל אביב,ירושלים,חיפה",
        help="רשימת ערים מופרדת בפסיקים (ל-Google)"
    )
    
    parser.add_argument(
        "--file",
        type=str,
        help="נתיב לקובץ CSV (למקור ידני)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="הרצה ללא שמירה במסד נתונים"
    )
    
    args = parser.parse_args()
    
    all_organizations = []
    
    # איסוף מ-Google Places
    if args.source in ["google", "both"]:
        if not settings.GOOGLE_PLACES_API_KEY:
            logger.error("חסר GOOGLE_PLACES_API_KEY בהגדרות")
            return
        
        collector = GooglePlacesCollector()
        cities = [c.strip() for c in args.cities.split(",")]
        
        for city in cities:
            logger.info(f"אוסף נתונים מ-{city}...")
            orgs = await collector.collect_from_city(city)
            all_organizations.extend(orgs)
            
            # המתנה בין ערים
            await asyncio.sleep(5)
    
    # איסוף מ-CSV
    if args.source in ["manual", "both"]:
        if not args.file:
            logger.error("חסר נתיב לקובץ CSV (--file)")
            return
        
        if not Path(args.file).exists():
            logger.error(f"קובץ לא קיים: {args.file}")
            return
        
        collector = ManualCSVCollector()
        orgs = await collector.collect_from_csv(args.file)
        all_organizations.extend(orgs)
    
    # סיכום
    logger.info(f"נאספו {len(all_organizations)} ארגונים")
    
    # ספירת ארגונים עם פרטי קשר
    with_phone = sum(1 for o in all_organizations if o.get("primary_phone"))
    with_email = sum(1 for o in all_organizations if o.get("email"))
    with_website = sum(1 for o in all_organizations if o.get("website"))
    
    logger.info(f"עם טלפון: {with_phone}")
    logger.info(f"עם מייל: {with_email}")
    logger.info(f"עם אתר: {with_website}")
    
    # שמירה במסד נתונים
    if not args.dry_run and all_organizations:
        saver = OrganizationSaver()
        stats = await saver.save_organizations(all_organizations)
        
        logger.info(
            f"סיכום שמירה: נוספו {stats['added']}, "
            f"עודכנו {stats['updated']}, נכשלו {stats['failed']}"
        )
    else:
        logger.info("מצב dry-run - לא נשמר במסד נתונים")
        
        # שמירה לקובץ JSON לבדיקה
        output_file = f"organizations_{datetime.now():%Y%m%d_%H%M%S}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_organizations, f, ensure_ascii=False, indent=2)
        
        logger.info(f"הנתונים נשמרו ל-{output_file}")


if __name__ == "__main__":
    asyncio.run(main())