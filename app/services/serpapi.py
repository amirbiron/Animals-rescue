"""
SerpAPI Integration Service
שירות אינטגרציה עם SerpAPI (Google Maps)

מטרות:
- למשוך פרטי קשר (טלפון, אתר) עבור עסקים/ארגונים לפי שם+עיר או לפי place_id
- אלטרנטיבה זולה יותר ל-Google Places Details לחילוץ פרטי קשר
"""

from typing import Any, Dict, List, Optional

import structlog
from serpapi import GoogleSearch

from app.core.config import settings


logger = structlog.get_logger(__name__).bind(component="serpapi")


class SerpAPIService:
    """
    שירות עבודה עם SerpAPI Google Maps.

    שימושים עיקריים:
    - חיפוש עסק לפי שם+עיר ומשיכת טלפון/אתר
    - משיכת פרטים לפי place_id (כאשר יש)
    """

    def __init__(self) -> None:
        self.api_key = settings.SERPAPI_KEY

    def _is_configured(self) -> bool:
        return bool(self.api_key)

    def get_contact_by_name_city(self, name: str, city: Optional[str] = None, country: str = "Israel") -> Optional[Dict[str, Any]]:
        """
        החזרת פרטי קשר לפי שם ו(אופציונלי) עיר.

        מחפש ב-engine=google_maps ומחזיר טלפון, אתר, כתובת ו-place_id אם נמצאו.
        """
        if not self._is_configured():
            logger.warning("SerpAPI key not configured")
            return None

        query = name
        if city:
            query = f"{name} {city}"

        params = {
            "engine": "google_maps",
            "q": query,
            "google_domain": "google.co.il",
            "hl": "he",
            "api_key": self.api_key,
        }

        try:
            search = GoogleSearch(params)
            results = search.get_dict()
            places: List[Dict[str, Any]] = results.get("local_results", []) or results.get("places_results", []) or []
            if not places:
                return None

            # בחר תוצאה ראשונה כמתאימה ביותר
            # Prefer mobile phone if possible
            from app.services.sms import is_israeli_mobile  # local import to avoid global dep
            selected = places[0]
            phone = selected.get("phone") or selected.get("extension")
            if not (phone and is_israeli_mobile(phone)):
                for p in places:
                    ph = p.get("phone") or p.get("extension")
                    if ph and is_israeli_mobile(ph):
                        selected = p
                        phone = ph
                        break
            return {
                "name": selected.get("title") or selected.get("name"),
                "phone": phone,
                "website": selected.get("website"),
                "address": selected.get("address"),
                "place_id": selected.get("place_id"),
                "rating": selected.get("rating"),
                "types": selected.get("type"),
            }
        except Exception as e:
            logger.error("SerpAPI search failed", error=str(e))
            return None

    def get_details_by_place_id(self, place_id: str) -> Optional[Dict[str, Any]]:
        """
        החזרת פרטי קשר לפי place_id (אם נתמך ב-SerpAPI לתוצאה).
        """
        if not self._is_configured():
            return None

        params = {
            "engine": "google_maps",
            "data_id": place_id,
            "google_domain": "google.co.il",
            "hl": "he",
            "api_key": self.api_key,
        }
        try:
            search = GoogleSearch(params)
            data = search.get_dict() or {}
            place = data.get("place_results") or {}
            if not place:
                return None
            from app.services.sms import is_israeli_mobile
            phone = place.get("phone")
            if phone and not is_israeli_mobile(phone):
                phone = None
            return {
                "name": place.get("title") or place.get("name"),
                "phone": phone,
                "website": place.get("website"),
                "address": place.get("address"),
                "place_id": place_id,
                "rating": place.get("rating"),
            }
        except Exception as e:
            logger.error("SerpAPI details failed", error=str(e))
            return None


__all__ = ["SerpAPIService"]

