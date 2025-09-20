"""
API Router v1
נתיב API גרסה 1

This module aggregates all API v1 routes and provides the main API router
that gets mounted to the FastAPI application in main.py.
"""

from fastapi import APIRouter

from app.api.v1.reports import router as reports_router
from app.core.config import settings
from app.api.v1.twilio_webhook import router as twilio_router

# =============================================================================
# Main API Router
# =============================================================================

api_router = APIRouter()

# =============================================================================
# Include Sub-Routers
# =============================================================================

# Reports API endpoints
api_router.include_router(
    reports_router,
    prefix="/reports",
    tags=["reports"],
    responses={
        404: {"description": "Report not found"},
        422: {"description": "Validation error"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
    },
)

# Twilio inbound webhook (SMS/WhatsApp)
api_router.include_router(
    twilio_router,
    prefix="/twilio",
    tags=["integrations"],
)

# Health check endpoint (simple)
@api_router.get("/health", tags=["system"])
async def api_health():
    """API health check endpoint."""
    return {
        "status": "healthy",
        "api_version": "v1",
        "service": settings.APP_NAME,
    }

# API Info endpoint
@api_router.get("/info", tags=["system"])
async def api_info():
    """API information endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": settings.APP_DESCRIPTION,
        "api_version": "v1",
        "environment": settings.ENVIRONMENT,
        "supported_languages": settings.SUPPORTED_LANGUAGES,
        "docs_url": "/docs" if settings.SHOW_DOCS else None,
    }

# TODO: Add more routers here as they are implemented
# Future routers to add:
# - Organizations router: /organizations
# - Users router: /users (admin only)
# - Alerts router: /alerts
# - Statistics router: /stats
# - Admin router: /admin

# Example of how to add future routers:
# from app.api.v1.organizations import router as organizations_router
# api_router.include_router(
#     organizations_router,
#     prefix="/organizations",
#     tags=["organizations"],
# )

# from app.api.v1.users import router as users_router
# api_router.include_router(
#     users_router,
#     prefix="/users",
#     tags=["users"],
#     dependencies=[Depends(require_roles([UserRole.SYSTEM_ADMIN]))],
# )

# from app.api.v1.alerts import router as alerts_router
# api_router.include_router(
#     alerts_router,
#     prefix="/alerts",
#     tags=["alerts"],
# )

# from app.api.v1.stats import router as stats_router
# api_router.include_router(
#     stats_router,
#     prefix="/stats",
#     tags=["statistics"],
# )

# from app.api.v1.admin import router as admin_router
# api_router.include_router(
#     admin_router,
#     prefix="/admin",
#     tags=["admin"],
#     dependencies=[Depends(require_roles([UserRole.SYSTEM_ADMIN]))],
# )
