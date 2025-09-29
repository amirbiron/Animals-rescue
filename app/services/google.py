"""
Google APIs Integration Service
שירות אינטגרציה עם Google APIs

This module provides integration with Google Maps, Places, and Geocoding APIs
for location services in the Animal Rescue Bot system. Includes rate limiting,
caching, and fallback mechanisms.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.cache import redis_client
from app.core.exceptions import ExternalServiceError, ValidationError

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# Google Service Integration
# =============================================================================

class GoogleService:
    """
    Comprehensive Google APIs service for location and places data.
    
    Features:
    - Places API integration for finding veterinary clinics
    - Geocoding API for address resolution
    - Rate limiting and quota management
    - Redis caching for API responses
    - Circuit breaker pattern for resilience
    - Fallback to cached data
    """
    
    def __init__(self):
        self.places_api_key = settings.GOOGLE_PLACES_API_KEY
        self.geocoding_api_key = settings.GOOGLE_GEOCODING_API_KEY or settings.GOOGLE_PLACES_API_KEY
        
        # API endpoints
        self.places_base_url = "https://maps.googleapis.com/maps/api/place"
        self.geocoding_base_url = "https://maps.googleapis.com/maps/api/geocode"
        
        # Rate limiting
        self.rate_limit = settings.GOOGLE_API_RATE_LIMIT
        self.daily_quota = settings.GOOGLE_API_QUOTA_DAILY
        
        # HTTP client with timeout and retry configuration
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
        )
        
        # Circuit breaker state
        self._circuit_breaker = {
            "failure_count": 0,
            "last_failure_time": 0,
            "is_open": False,
            "threshold": 5,  # Number of failures before opening
            "timeout": 300,  # 5 minutes before trying again
        }
        # User agent for external services (e.g., OSM/Nominatim)
        self._user_agent = f"{settings.APP_NAME}/{settings.APP_VERSION}"
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    # =========================================================================
    # Rate Limiting and Circuit Breaker
    # =========================================================================
    
    async def _check_rate_limit(self) -> bool:
        """Check if we're within API rate limits."""
        current_time = time.time()
        minute_key = f"google_api_rate_limit:{int(current_time // 60)}"
        daily_key = f"google_api_daily_quota:{time.strftime('%Y-%m-%d')}"
        
        # Check minute rate limit
        current_minute_count = await redis_client.get(minute_key)
        if current_minute_count and int(current_minute_count) >= self.rate_limit * 60:
            logger.warning("Google API minute rate limit exceeded")
            return False
        
        # Check daily quota
        current_daily_count = await redis_client.get(daily_key)
        if current_daily_count and int(current_daily_count) >= self.daily_quota:
            logger.warning("Google API daily quota exceeded")
            return False
        
        return True
    
    async def _increment_usage(self):
        """Increment API usage counters."""
        current_time = time.time()
        minute_key = f"google_api_rate_limit:{int(current_time // 60)}"
        daily_key = f"google_api_daily_quota:{time.strftime('%Y-%m-%d')}"
        
        # Increment counters with expiration
        await redis_client.incr(minute_key)
        await redis_client.expire(minute_key, 60)
        
        await redis_client.incr(daily_key)
        await redis_client.expire(daily_key, 86400)  # 24 hours
    
    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open."""
        if not self._circuit_breaker["is_open"]:
            return False
        
        # Check if timeout has passed
        current_time = time.time()
        if current_time - self._circuit_breaker["last_failure_time"] > self._circuit_breaker["timeout"]:
            logger.info("Circuit breaker timeout passed, attempting to close")
            self._circuit_breaker["is_open"] = False
            self._circuit_breaker["failure_count"] = 0
            return False
        
        return True
    
    def _record_success(self):
        """Record successful API call."""
        self._circuit_breaker["failure_count"] = 0
        if self._circuit_breaker["is_open"]:
            logger.info("Circuit breaker closed after successful request")
            self._circuit_breaker["is_open"] = False
    
    def _record_failure(self):
        """Record failed API call."""
        self._circuit_breaker["failure_count"] += 1
        self._circuit_breaker["last_failure_time"] = time.time()
        
        if self._circuit_breaker["failure_count"] >= self._circuit_breaker["threshold"]:
            logger.warning(
                "Circuit breaker opened due to repeated failures",
                failure_count=self._circuit_breaker["failure_count"]
            )
            self._circuit_breaker["is_open"] = True
    
    # =========================================================================
    # Caching Utilities
    # =========================================================================
    
    def _get_cache_key(self, service: str, **params) -> str:
        """Generate cache key for API response."""
        # Sort params for consistent keys
        sorted_params = sorted(params.items())
        param_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        # Create hash for long parameters
        param_hash = hashlib.md5(param_string.encode()).hexdigest()
        
        return f"google_{service}:{param_hash}"
    
    async def _get_cached_response(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached API response."""
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.warning("Failed to retrieve cached response", error=str(e))
        
        return None
    
    async def _cache_response(self, cache_key: str, data: Dict[str, Any], ttl: int = 3600):
        """Cache API response."""
        try:
            await redis_client.setex(cache_key, ttl, json.dumps(data, default=str))
        except Exception as e:
            logger.warning("Failed to cache response", error=str(e))
    
    # =========================================================================
    # Places API Integration
    # =========================================================================
    
    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def search_places(
        self,
        query: str,
        location: Optional[Tuple[float, float]] = None,
        radius: int = 10000,
        place_type: Optional[str] = None,
        language: str = "he"
    ) -> List[Dict[str, Any]]:
        """
        Search for places using Google Places API.
        
        Args:
            query: Search query (e.g., "veterinary clinic")
            location: (latitude, longitude) for location-based search
            radius: Search radius in meters (max 50000)
            place_type: Google Places type filter
            language: Response language
            
        Returns:
            List of place data dictionaries
            
        Raises:
            ExternalServiceError: If API call fails
        """
        if not self.places_api_key:
            raise ExternalServiceError("Google Places API key not configured")
        
        # Check circuit breaker
        if self._is_circuit_breaker_open():
            logger.warning("Circuit breaker open, falling back to cache")
            return await self._get_fallback_places(query, location)
        
        # Check rate limits
        if not await self._check_rate_limit():
            logger.warning("Rate limit exceeded, falling back to cache")
            return await self._get_fallback_places(query, location)
        
        # Prepare cache key
        cache_params = {
            "query": query,
            "location": f"{location[0]},{location[1]}" if location else "",
            "radius": radius,
            "type": place_type or "",
            "language": language,
        }
        cache_key = self._get_cache_key("places_search", **cache_params)
        
        # Check cache first
        cached_response = await self._get_cached_response(cache_key)
        if cached_response:
            logger.debug("Returning cached places search result")
            return cached_response
        
        try:
            # Build API request
            params = {
                "query": query,
                "key": self.places_api_key,
                "language": language,
                "fields": "place_id,name,formatted_address,geometry,rating,opening_hours,formatted_phone_number,website,types"
            }
            
            if location:
                params["location"] = f"{location[0]},{location[1]}"
                params["radius"] = min(radius, 50000)  # API limit
            
            if place_type:
                params["type"] = place_type
            
            # Make API request
            url = f"{self.places_base_url}/textsearch/json"
            
            logger.debug("Making Google Places API request", params=params)
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            await self._increment_usage()
            
            data = response.json()
            
            if data.get("status") != "OK":
                error_message = data.get("error_message", "Unknown API error")
                logger.error("Google Places API error", status=data.get("status"), error=error_message)
                
                if data.get("status") == "OVER_QUERY_LIMIT":
                    self._record_failure()
                    return await self._get_fallback_places(query, location)
                
                raise ExternalServiceError(f"Google Places API error: {error_message}")
            
            # Process results
            places = []
            for result in data.get("results", []):
                place_data = self._process_place_result(result)
                places.append(place_data)
            
            # Cache results for 1 hour
            await self._cache_response(cache_key, places, ttl=3600)
            
            self._record_success()
            
            logger.info(
                "Places search completed",
                query=query,
                results_count=len(places),
                location=location
            )
            
            return places
            
        except httpx.HTTPStatusError as e:
            self._record_failure()
            logger.error("Google Places API HTTP error", status_code=e.response.status_code, error=str(e))
            
            # Try fallback
            fallback_results = await self._get_fallback_places(query, location)
            if fallback_results:
                return fallback_results
            
            raise ExternalServiceError(f"Google Places API error: {e}")
        
        except Exception as e:
            self._record_failure()
            logger.error("Google Places API request failed", error=str(e), exc_info=True)
            
            # Try fallback
            fallback_results = await self._get_fallback_places(query, location)
            if fallback_results:
                return fallback_results
            
            raise ExternalServiceError(f"Google Places API request failed: {e}")
    
    async def _enrich_places_details(
        self,
        places: List[Dict[str, Any]],
        language: str = "he",
        concurrency: int = 5,
    ) -> List[Dict[str, Any]]:
        """Enrich a list of Places with phone/website by calling Place Details for missing fields.

        Only calls details for items missing phone/website. Uses a small concurrency limit and relies on caching.
        """
        if not places:
            return places

        sem = asyncio.Semaphore(concurrency)
        enriched: List[Dict[str, Any]] = []

        async def _enrich_one(item: Dict[str, Any]) -> Dict[str, Any]:
            phone_missing = not item.get("phone")
            website_missing = not item.get("website")
            place_id = item.get("place_id")
            if not place_id or not (phone_missing or website_missing):
                return item
            async with sem:
                try:
                    details = await self.get_place_details(place_id, language=language)
                    if details:
                        merged = item.copy()
                        for k in ("phone", "website", "opening_hours", "types"):
                            v = details.get(k)
                            if v and not merged.get(k):
                                merged[k] = v
                        # Filter: prefer mobile numbers for SMS/WhatsApp. If phone seems landline, try to drop it.
                        try:
                            from app.services.sms import is_israeli_mobile  # local import to avoid cycles
                            ph = merged.get("phone")
                            if ph and not is_israeli_mobile(ph):
                                # keep website but drop landline phone to force later enrichment or manual update
                                merged.pop("phone", None)
                        except Exception:
                            pass
                        return merged
                except Exception:
                    pass
                return item

        tasks = [_enrich_one(p) for p in places]
        enriched = await asyncio.gather(*tasks)
        return list(enriched)

    def _process_place_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single place result from Google Places API."""
        geometry = result.get("geometry", {})
        location = geometry.get("location", {})
        
        # Extract opening hours
        opening_hours = None
        if "opening_hours" in result:
            hours_data = result["opening_hours"]
            opening_hours = {
                "open_now": hours_data.get("open_now"),
                "periods": hours_data.get("periods", []),
                "weekday_text": hours_data.get("weekday_text", [])
            }
        
        return {
            "place_id": result.get("place_id"),
            "name": result.get("name"),
            "address": result.get("formatted_address"),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
            "rating": result.get("rating"),
            "phone": result.get("formatted_phone_number"),
            "website": result.get("website"),
            "types": result.get("types", []),
            "opening_hours": opening_hours,
            "price_level": result.get("price_level"),
        }
    
    async def get_place_details(
        self, 
        place_id: str, 
        language: str = "he",
        fields: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific place.
        
        Args:
            place_id: Google Places place ID
            language: Response language
            fields: Specific fields to retrieve
            
        Returns:
            Detailed place information or None if not found
        """
        if not self.places_api_key:
            raise ExternalServiceError("Google Places API key not configured")
        
        # Check circuit breaker
        if self._is_circuit_breaker_open():
            return await self._get_cached_place_details(place_id)
        
        # Check rate limits
        if not await self._check_rate_limit():
            return await self._get_cached_place_details(place_id)
        
        # Prepare cache key
        cache_key = self._get_cache_key("place_details", place_id=place_id, language=language)
        
        # Check cache
        cached_response = await self._get_cached_response(cache_key)
        if cached_response:
            return cached_response
        
        try:
            # Default fields if none specified
            if not fields:
                fields = [
                    "place_id", "name", "formatted_address", "geometry",
                    "formatted_phone_number", "website", "opening_hours",
                    "rating", "user_ratings_total", "types", "photos"
                ]
            
            params = {
                "place_id": place_id,
                "fields": ",".join(fields),
                "key": self.places_api_key,
                "language": language,
            }
            
            url = f"{self.places_base_url}/details/json"
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            await self._increment_usage()
            
            data = response.json()
            
            if data.get("status") != "OK":
                if data.get("status") == "NOT_FOUND":
                    return None
                
                error_message = data.get("error_message", "Unknown API error")
                logger.error("Google Places details API error", error=error_message)
                
                if data.get("status") == "OVER_QUERY_LIMIT":
                    self._record_failure()
                    return await self._get_cached_place_details(place_id)
                
                raise ExternalServiceError(f"Google Places API error: {error_message}")
            
            # Process result
            result = data.get("result", {})
            place_details = self._process_place_result(result)
            
            # Cache for 24 hours (place details change less frequently)
            await self._cache_response(cache_key, place_details, ttl=86400)
            
            self._record_success()
            
            logger.debug("Place details retrieved", place_id=place_id)
            
            return place_details
            
        except Exception as e:
            self._record_failure()
            logger.error("Failed to get place details", place_id=place_id, error=str(e))
            
            # Try cached version
            return await self._get_cached_place_details(place_id)
    
    async def search_veterinary_clinics(
        self,
        city: str,
        radius: int = 15000,
        language: str = "he"
    ) -> List[Dict[str, Any]]:
        """
        Search for veterinary clinics in a specific city.
        
        Args:
            city: City name to search in
            radius: Search radius in meters
            language: Response language
            
        Returns:
            List of veterinary clinics
        """
        # First, geocode the city to get coordinates
        city_location = await self.geocode(city, language=language)
        if not city_location:
            logger.warning("Could not geocode city for veterinary search", city=city)
            return []
        
        location = (city_location["latitude"], city_location["longitude"])
        
        # Search terms in multiple languages
        search_terms = [
            f"veterinary clinic {city}",
            f"וטרינר {city}",
            f"מרפאה וטרינרית {city}",
            f"בית חולים וטרינרי {city}",
        ]
        
        all_results = []
        seen_place_ids = set()
        
        for term in search_terms:
            try:
                results = await self.search_places(
                    query=term,
                    location=location,
                    radius=radius,
                    place_type="veterinary_care",
                    language=language
                )
                
                # Filter for veterinary-related results and remove duplicates
                for result in results:
                    place_id = result.get("place_id")
                    if place_id and place_id not in seen_place_ids:
                        types = result.get("types", [])
                        name = result.get("name", "").lower()
                        
                        # Check if it's actually a veterinary clinic
                        if (any(vet_type in types for vet_type in ["veterinary_care", "hospital"]) or
                            any(keyword in name for keyword in ["vet", "וטרינר", "מרפאה", "בית חולים"])):
                            
                            all_results.append(result)
                            seen_place_ids.add(place_id)
                
                # Small delay between searches
                await asyncio.sleep(0.2)
                
            except Exception as e:
                logger.warning("Veterinary search failed for term", term=term, error=str(e))
                continue
        
        logger.info(
            "Veterinary clinics search completed",
            city=city,
            total_results=len(all_results)
        )
        all_results = await self._enrich_places_details(all_results, language=language)
        return all_results

    async def search_animal_shelters(
        self,
        city: str,
        radius: int = 15000,
        language: str = "he"
    ) -> List[Dict[str, Any]]:
        """
        Search for animal shelters, rescue organizations and volunteer groups in a specific city.
        """
        city_location = await self.geocode(city, language=language)
        if not city_location:
            logger.warning("Could not geocode city for shelter search", city=city)
            return []
        location = (city_location["latitude"], city_location["longitude"]) 
        search_terms = [
            # English
            f"animal shelter {city}",
            f"pet rescue {city}",
            f"animal rescue {city}",
            f"rescue group {city}",
            f"volunteer animal rescue {city}",
            f"animal adoption {city}",
            f"dog shelter {city}",
            f"cat shelter {city}",
            f"humane society {city}",
            # Hebrew
            f"עמותת בעלי חיים {city}",
            f"עמותה להצלת בעלי חיים {city}",
            f"הצלת בעלי חיים {city}",
            f"חילוץ בעלי חיים {city}",
            f"קבוצת חילוץ בעלי חיים {city}",
            f"מתנדבי חילוץ בעלי חיים {city}",
            f"מתנדבים בעלי חיים {city}",
            f"מקלט לבעלי חיים {city}",
            f"כלביה {city}",
            f"חתוליה {city}",
            f"אימוץ בעלי חיים {city}",
            f"צער בעלי חיים {city}",
            f"תנו לחיות לחיות {city}",
        ]
        all_results: List[Dict[str, Any]] = []
        seen_place_ids: set[str] = set()
        for term in search_terms:
            try:
                results = await self.search_places(
                    query=term,
                    location=location,
                    radius=radius,
                    language=language
                )
                for result in results:
                    place_id = result.get("place_id")
                    if place_id and place_id not in seen_place_ids:
                        types = result.get("types", [])
                        name = (result.get("name") or "").lower()
                        # Heuristics: shelter/rescue/volunteer/adoption keywords or known types
                        keywords = [
                            "shelter", "rescue", "volunteer", "adoption", "humane", "pound",
                            "עמותה", "עמותת", "מקלט", "כלביה", "כלבייה", "חתוליה", "חילוץ", "הצלה", "אימוץ",
                            "מתנדב", "מתנדבים",
                            "צער בעלי חיים", "תנו לחיות לחיות",
                        ]
                        if (
                            any(k in name for k in keywords) or
                            any(t in types for t in ["animal_shelter"]) 
                        ):
                            all_results.append(result)
                            seen_place_ids.add(place_id)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning("Shelter search failed for term", term=term, error=str(e))
                continue
        logger.info("Animal shelters search completed", city=city, total_results=len(all_results))
        all_results = await self._enrich_places_details(all_results, language=language)
        return all_results

    async def search_veterinary_nearby(
        self,
        location: Tuple[float, float],
        radius: int = 15000,
        language: str = "he",
    ) -> List[Dict[str, Any]]:
        """Search for veterinary clinics near coordinates."""
        all_results: List[Dict[str, Any]] = []
        seen_place_ids: set[str] = set()
        for term in ["veterinary clinic", "וטרינר", "מרפאה וטרינרית", "vet"]:
            try:
                results = await self.search_places(
                    query=term,
                    location=location,
                    radius=radius,
                    place_type="veterinary_care",
                    language=language,
                )
                for result in results:
                    place_id = result.get("place_id")
                    if place_id and place_id not in seen_place_ids:
                        types = result.get("types", [])
                        name = (result.get("name") or "").lower()
                        if (
                            any(vet_type in types for vet_type in ["veterinary_care", "hospital"]) or
                            any(keyword in name for keyword in ["vet", "וטרינר", "מרפאה", "hospital"])):
                            all_results.append(result)
                            seen_place_ids.add(place_id)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning("Veterinary nearby search failed", error=str(e))
                continue
        all_results = await self._enrich_places_details(all_results, language=language)
        return all_results

    async def search_shelters_nearby(
        self,
        location: Tuple[float, float],
        radius: int = 15000,
        language: str = "he",
    ) -> List[Dict[str, Any]]:
        """Search for animal shelters and rescues near coordinates."""
        all_results: List[Dict[str, Any]] = []
        seen_place_ids: set[str] = set()
        for term in ["animal shelter", "pet rescue", "עמותת בעלי חיים", "מקלט לבעלי חיים"]:
            try:
                results = await self.search_places(
                    query=term,
                    location=location,
                    radius=radius,
                    language=language,
                )
                for result in results:
                    place_id = result.get("place_id")
                    if place_id and place_id not in seen_place_ids:
                        types = result.get("types", [])
                        name = (result.get("name") or "").lower()
                        if (
                            any(k in name for k in ["shelter", "rescue", "עמותה", "מקלט"]) or
                            any(t in types for t in ["animal_shelter"])):
                            all_results.append(result)
                            seen_place_ids.add(place_id)
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning("Shelter nearby search failed", error=str(e))
                continue
        all_results = await self._enrich_places_details(all_results, language=language)
        return all_results
    
    # =========================================================================
    # Geocoding API Integration
    # =========================================================================
    
    async def geocode(
        self,
        address: str,
        language: str = "he",
        region: str = "il"
    ) -> Optional[Dict[str, Any]]:
        """
        Convert address to coordinates using Google Geocoding API.
        
        Args:
            address: Address to geocode
            language: Response language
            region: Country/region bias
            
        Returns:
            Geocoding result with coordinates and address components
        """
        if not self.geocoding_api_key:
            logger.warning("Google Geocoding API key not configured")
            # Fallback to OpenStreetMap Nominatim
            return await self._fallback_geocode_osm(address, language=language, region=region)
        
        # Check circuit breaker
        if self._is_circuit_breaker_open():
            return await self._get_cached_geocoding(address, language)
        
        # Check rate limits
        if not await self._check_rate_limit():
            return await self._get_cached_geocoding(address, language)
        
        # Prepare cache key
        cache_key = self._get_cache_key("geocoding", address=address, language=language, region=region)
        
        # Check cache
        cached_response = await self._get_cached_response(cache_key)
        if cached_response:
            return cached_response
        
        try:
            params = {
                "address": address,
                "key": self.geocoding_api_key,
                "language": language,
                "region": region,
            }
            
            url = f"{self.geocoding_base_url}/json"
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            await self._increment_usage()
            
            data = response.json()
            
            if data.get("status") != "OK":
                if data.get("status") == "ZERO_RESULTS":
                    # Try fallback to OSM which might have better local coverage
                    fallback = await self._fallback_geocode_osm(address, language=language, region=region)
                    return fallback
                
                error_message = data.get("error_message", "Unknown API error")
                logger.error("Google Geocoding API error", error=error_message, status=data.get("status"))
                
                if data.get("status") in {"OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR"}:
                    self._record_failure()
                    # Try OSM fallback before giving up
                    fallback = await self._fallback_geocode_osm(address, language=language, region=region)
                    if fallback:
                        return fallback
                    return await self._get_cached_geocoding(address, language)
                
                raise ExternalServiceError(f"Google Geocoding API error: {error_message}")
            
            # Process first result
            results = data.get("results", [])
            if not results:
                return None
            
            result = results[0]
            geometry = result.get("geometry", {})
            location = geometry.get("location", {})
            
            # Extract address components
            components = {}
            for component in result.get("address_components", []):
                types = component.get("types", [])
                if "locality" in types:
                    components["city"] = component.get("long_name")
                elif "country" in types:
                    components["country"] = component.get("long_name")
                elif "administrative_area_level_1" in types:
                    components["state"] = component.get("long_name")
                elif "postal_code" in types:
                    components["postal_code"] = component.get("long_name")
            
            geocoding_result = {
                "latitude": location.get("lat"),
                "longitude": location.get("lng"),
                "formatted_address": result.get("formatted_address"),
                "components": components,
                "location_type": geometry.get("location_type"),
                "confidence": self._calculate_geocoding_confidence(result),
            }
            
            # Cache for 24 hours
            await self._cache_response(cache_key, geocoding_result, ttl=86400)
            
            self._record_success()
            
            logger.debug("Geocoding completed", address=address)
            
            return geocoding_result
            
        except Exception as e:
            self._record_failure()
            logger.error("Geocoding failed", address=address, error=str(e))
            
            # Try OSM fallback, then cached version
            try:
                fallback = await self._fallback_geocode_osm(address, language=language, region=region)
                if fallback:
                    return fallback
            except Exception:
                pass
            return await self._get_cached_geocoding(address, language)
    
    async def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        language: str = "he"
    ) -> Optional[Dict[str, Any]]:
        """
        Convert coordinates to address using Google Geocoding API.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            language: Response language
            
        Returns:
            Reverse geocoding result with address information
        """
        if not self.geocoding_api_key:
            logger.warning("Google Geocoding API key not configured")
            # Fallback to OpenStreetMap Nominatim
            return await self._fallback_reverse_geocode_osm(latitude, longitude, language=language)
        
        # Check circuit breaker
        if self._is_circuit_breaker_open():
            return await self._get_cached_reverse_geocoding(latitude, longitude, language)
        
        # Check rate limits
        if not await self._check_rate_limit():
            return await self._get_cached_reverse_geocoding(latitude, longitude, language)
        
        # Prepare cache key
        cache_key = self._get_cache_key("reverse_geocoding", lat=latitude, lng=longitude, language=language)
        
        # Check cache
        cached_response = await self._get_cached_response(cache_key)
        if cached_response:
            return cached_response
        
        try:
            params = {
                "latlng": f"{latitude},{longitude}",
                "key": self.geocoding_api_key,
                "language": language,
            }
            
            url = f"{self.geocoding_base_url}/json"
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            
            await self._increment_usage()
            
            data = response.json()
            
            if data.get("status") != "OK":
                if data.get("status") == "ZERO_RESULTS":
                    # Fallback to OSM which may return neighborhood/road
                    return await self._fallback_reverse_geocode_osm(latitude, longitude, language=language)
                
                error_message = data.get("error_message", "Unknown API error")
                logger.error("Google Reverse Geocoding API error", error=error_message, status=data.get("status"))
                
                if data.get("status") in {"OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR"}:
                    self._record_failure()
                    # Try OSM fallback first
                    try:
                        fallback = await self._fallback_reverse_geocode_osm(latitude, longitude, language=language)
                        if fallback:
                            return fallback
                    except Exception:
                        pass
                    return await self._get_cached_reverse_geocoding(latitude, longitude, language)
                
                raise ExternalServiceError(f"Google Reverse Geocoding API error: {error_message}")
            
            # Process results - prefer the most specific result
            results = data.get("results", [])
            if not results:
                return None
            
            # Find best result (prefer street address over general area)
            best_result = None
            for result in results:
                types = result.get("types", [])
                if "street_address" in types or "premise" in types:
                    best_result = result
                    break
                elif not best_result and "route" in types:
                    best_result = result
                elif not best_result:
                    best_result = result
            
            result = best_result or results[0]
            
            # Extract address components
            components = {}
            for component in result.get("address_components", []):
                types = component.get("types", [])
                if "locality" in types:
                    components["city"] = component.get("long_name")
                elif "country" in types:
                    components["country"] = component.get("long_name")
                elif "administrative_area_level_1" in types:
                    components["state"] = component.get("long_name")
                elif "postal_code" in types:
                    components["postal_code"] = component.get("long_name")
            
            reverse_geocoding_result = {
                "formatted_address": result.get("formatted_address"),
                "address": result.get("formatted_address"),
                "city": components.get("city"),
                "components": components,
                "location_type": result.get("geometry", {}).get("location_type"),
                "confidence": self._calculate_geocoding_confidence(result),
            }
            
            # Cache for 24 hours
            await self._cache_response(cache_key, reverse_geocoding_result, ttl=86400)
            
            self._record_success()
            
            logger.debug("Reverse geocoding completed", lat=latitude, lng=longitude)
            
            return reverse_geocoding_result
            
        except Exception as e:
            self._record_failure()
            logger.error("Reverse geocoding failed", lat=latitude, lng=longitude, error=str(e))
            
            # Try OSM fallback, then cached version
            try:
                fallback = await self._fallback_reverse_geocode_osm(latitude, longitude, language=language)
                if fallback:
                    return fallback
            except Exception:
                pass
            return await self._get_cached_reverse_geocoding(latitude, longitude, language)

    async def _fallback_geocode_osm(
        self,
        address: str,
        language: str = "he",
        region: Optional[str] = "il",
    ) -> Optional[Dict[str, Any]]:
        """Fallback geocoding using OpenStreetMap Nominatim service."""
        try:
            params = {
                "q": address,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
                "accept-language": language,
            }
            if region:
                params["countrycodes"] = region
            headers = {"User-Agent": self._user_agent}
            url = "https://nominatim.openstreetmap.org/search"
            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            results = response.json()
            if not results:
                return None
            item = results[0]
            address_dict = item.get("address", {}) or {}
            city = address_dict.get("city") or address_dict.get("town") or address_dict.get("village")
            confidence = 0.6 if item.get("type") in {"house", "building", "address"} else 0.5
            return {
                "latitude": float(item.get("lat")),
                "longitude": float(item.get("lon")),
                "formatted_address": item.get("display_name"),
                "address": item.get("display_name"),
                "components": {
                    "city": city,
                    "country": address_dict.get("country"),
                    "state": address_dict.get("state"),
                    "postal_code": address_dict.get("postcode"),
                },
                "location_type": item.get("type"),
                "confidence": confidence,
                "city": city,
            }
        except Exception as e:
            logger.warning("OSM geocoding fallback failed", error=str(e))
            return None

    async def _fallback_reverse_geocode_osm(
        self,
        latitude: float,
        longitude: float,
        language: str = "he",
    ) -> Optional[Dict[str, Any]]:
        """Fallback reverse geocoding using OpenStreetMap Nominatim service."""
        try:
            params = {
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "addressdetails": 1,
                "accept-language": language,
            }
            headers = {"User-Agent": self._user_agent}
            url = "https://nominatim.openstreetmap.org/reverse"
            response = await self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            address_dict = (data or {}).get("address", {}) or {}
            city = address_dict.get("city") or address_dict.get("town") or address_dict.get("village")
            display_name = (data or {}).get("display_name")
            # Confidence heuristic
            confidence = 0.6 if address_dict.get("house_number") else 0.5
            return {
                "formatted_address": display_name,
                "address": display_name,
                "city": city,
                "components": {
                    "city": city,
                    "country": address_dict.get("country"),
                    "state": address_dict.get("state"),
                    "postal_code": address_dict.get("postcode"),
                },
                "location_type": data.get("type"),
                "confidence": confidence,
            }
        except Exception as e:
            logger.warning("OSM reverse geocoding fallback failed", error=str(e))
            return None
    
    def _calculate_geocoding_confidence(self, result: Dict[str, Any]) -> float:
        """Calculate confidence score for geocoding result."""
        location_type = result.get("geometry", {}).get("location_type", "")
        
        # Confidence based on location type
        confidence_map = {
            "ROOFTOP": 0.9,
            "RANGE_INTERPOLATED": 0.8,
            "GEOMETRIC_CENTER": 0.7,
            "APPROXIMATE": 0.5,
        }
        
        confidence = confidence_map.get(location_type, 0.5)
        
        # Boost confidence if result has specific types
        types = result.get("types", [])
        if any(t in types for t in ["street_address", "premise", "subpremise"]):
            confidence = min(1.0, confidence + 0.1)
        
        return confidence
    
    # =========================================================================
    # Fallback and Cache Management
    # =========================================================================
    
    async def _get_fallback_places(
        self, 
        query: str, 
        location: Optional[Tuple[float, float]]
    ) -> List[Dict[str, Any]]:
        """Get fallback places data from cache or database."""
        # Try to find cached results with broader criteria
        fallback_keys = [
            self._get_cache_key("places_search", query=query.split()[0]),  # First word only
            self._get_cache_key("places_search", query="veterinary"),  # Generic vet search
        ]
        
        for key in fallback_keys:
            cached_data = await self._get_cached_response(key)
            if cached_data:
                logger.info("Using fallback cached data", query=query)
                return cached_data
        
        # Could also implement database fallback here
        logger.warning("No fallback data available", query=query)
        return []
    
    async def _get_cached_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Get cached place details."""
        cache_key = self._get_cache_key("place_details", place_id=place_id)
        return await self._get_cached_response(cache_key)
    
    async def _get_cached_geocoding(self, address: str, language: str) -> Optional[Dict[str, Any]]:
        """Get cached geocoding result."""
        cache_key = self._get_cache_key("geocoding", address=address, language=language)
        return await self._get_cached_response(cache_key)
    
    async def _get_cached_reverse_geocoding(
        self, 
        latitude: float, 
        longitude: float, 
        language: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached reverse geocoding result."""
        cache_key = self._get_cache_key("reverse_geocoding", lat=latitude, lng=longitude, language=language)
        return await self._get_cached_response(cache_key)
    
    # =========================================================================
    # Service Health and Testing
    # =========================================================================
    
    async def test_connection(self) -> bool:
        """Test connection to Google APIs."""
        if not self.places_api_key:
            return False
        
        try:
            # Simple test request
            params = {
                "query": "Tel Aviv",
                "key": self.places_api_key,
                "language": "en",
            }
            
            url = f"{self.places_base_url}/textsearch/json"
            response = await self.client.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("status") in ["OK", "ZERO_RESULTS"]
            
            return False
            
        except Exception as e:
            logger.error("Google API connection test failed", error=str(e))
            return False
    
    async def get_service_status(self) -> Dict[str, Any]:
        """Get current service status and statistics."""
        current_time = time.time()
        daily_key = f"google_api_daily_quota:{time.strftime('%Y-%m-%d')}"
        
        # Get usage statistics
        daily_usage = await redis_client.get(daily_key)
        daily_usage = int(daily_usage) if daily_usage else 0
        
        return {
            "service_available": not self._is_circuit_breaker_open(),
            "api_configured": bool(self.places_api_key),
            "daily_usage": daily_usage,
            "daily_quota": self.daily_quota,
            "quota_remaining": max(0, self.daily_quota - daily_usage),
            "circuit_breaker": {
                "is_open": self._circuit_breaker["is_open"],
                "failure_count": self._circuit_breaker["failure_count"],
                "last_failure_time": self._circuit_breaker["last_failure_time"],
            },
        }


# =============================================================================
# Geocoding Service Class (Simplified Interface)
# =============================================================================

class GeocodingService:
    """
    Simplified geocoding service interface.
    
    Provides a clean interface for geocoding operations used throughout
    the application.
    """
    
    def __init__(self):
        self.google_service = GoogleService()
        # Simple in-memory cache for reverse geocoding
        self._rev_cache: Dict[str, Dict[str, Any]] = {}
    
    async def geocode(self, address: str, language: str = "he") -> Optional[Dict[str, Any]]:
        """Geocode an address to coordinates."""
        async with self.google_service:
            return await self.google_service.geocode(address, language)
    
    async def reverse_geocode(
        self, 
        latitude: float, 
        longitude: float, 
        language: str = "he"
    ) -> Optional[Dict[str, Any]]:
        """Reverse geocode coordinates to address.
        Tries Google first, then falls back to Nominatim if missing city/address.
        Caches successful lookups in-memory.
        """
        key = f"{round(latitude, 6)}:{round(longitude, 6)}:{language}"
        if key in self._rev_cache:
            return self._rev_cache[key]
        result: Optional[Dict[str, Any]] = None
        async with self.google_service:
            try:
                result = await self.google_service.reverse_geocode(latitude, longitude, language)
            except Exception:
                result = None
        # If Google failed or city/address missing, fallback to Nominatim
        needs_fallback = (
            not result or not (result.get("city") or result.get("address") or result.get("formatted_address"))
        )
        if needs_fallback:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(
                        "https://nominatim.openstreetmap.org/reverse",
                        params={
                            "lat": latitude,
                            "lon": longitude,
                            "format": "jsonv2",
                            "accept-language": language,
                        },
                        headers={"User-Agent": f"{settings.APP_NAME}/{settings.APP_VERSION}"}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        address = data.get("display_name")
                        components = data.get("address", {})
                        city = components.get("city") or components.get("town") or components.get("village") or components.get("municipality")
                        fallback = {
                            "address": address,
                            "formatted_address": address,
                            "city": city,
                            "components": components,
                        }
                        # If Google had partial, merge
                        if result:
                            result.update({k: v for k, v in fallback.items() if v})
                        else:
                            result = fallback
            except Exception as e:
                logger.warning("Nominatim reverse geocode failed", error=str(e))
        if result:
            self._rev_cache[key] = result
        return result
    
    async def batch_geocode(
        self, 
        addresses: List[str], 
        language: str = "he"
    ) -> List[Optional[Dict[str, Any]]]:
        """Geocode multiple addresses with rate limiting."""
        results = []
        
        async with self.google_service:
            for address in addresses:
                try:
                    result = await self.google_service.geocode(address, language)
                    results.append(result)
                    
                    # Rate limiting delay
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error("Batch geocoding failed for address", address=address, error=str(e))
                    results.append(None)
        
        return results


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "GoogleService",
    "GeocodingService",
]
