"""
Shim לשמירת תאימות לייבוא geocoding.

מייצא את GeocodingService מקובץ google כך שייבוא
"from app.services.geocoding import GeocodingService" יעבוד.
"""

from app.services.google import GeocodingService

__all__ = ["GeocodingService"]

