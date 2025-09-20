"""
Telegram Bot Webhook Router
נתיב Webhook לבוט טלגרם

This module provides HTTP webhook endpoints for receiving Telegram updates
and routing them to the bot application handlers.
"""

import json
from typing import Any, Dict

import structlog
from fastapi import APIRouter, HTTPException, Request, Response, status
from telegram import Update

from app.bot.handlers import bot_application
from app.core.config import settings

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# Webhook Router
# =============================================================================

telegram_router = APIRouter()

# =============================================================================
# Webhook Endpoints
# =============================================================================

@telegram_router.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    """
    Handle incoming Telegram webhook updates.
    
    This endpoint receives updates from Telegram servers and processes them
    through the bot application handlers.
    
    Returns:
        200 OK response to acknowledge receipt
    """
    try:
        # Verify webhook secret if configured
        if settings.TELEGRAM_WEBHOOK_SECRET:
            secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_header != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning(
                    "Invalid webhook secret",
                    provided=secret_header,
                    remote_addr=request.client.host
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook secret"
                )
        
        # Parse request body
        try:
            body = await request.body()
            if not body:
                logger.warning("Empty webhook request body")
                return Response(status_code=200)
            
            # Parse JSON
            update_data = json.loads(body.decode('utf-8'))
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse webhook JSON", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON in request body"
            )
        except Exception as e:
            logger.error("Failed to read webhook request", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to read request body"
            )
        
        # Create Telegram Update object
        try:
            update = Update.de_json(update_data, bot_application.bot)
            if not update:
                logger.warning("Failed to create Update object", data=update_data)
                return Response(status_code=200)
            
        except Exception as e:
            logger.error("Failed to create Update object", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid update format"
            )
        
        # Log update info – extended to cover all types
        update_info = {"has_message": bool(update.message), "has_callback": bool(update.callback_query)}
        if update.message:
            update_info.update({
                "message_id": update.message.message_id,
                "user_id": update.message.from_user.id if update.message.from_user else None,
                "chat_id": update.message.chat.id,
                "text_preview": update.message.text[:50] if update.message.text else None,
                "has_location": bool(getattr(update.message, 'location', None)),
                "has_photo": bool(getattr(update.message, 'photo', None)),
                "has_contact": bool(getattr(update.message, 'contact', None)),
                "has_venue": bool(getattr(update.message, 'venue', None)),
            })
            if update.message.location:
                update_info.update({
                    "latitude": update.message.location.latitude,
                    "longitude": update.message.location.longitude,
                })
        if update.callback_query:
            update_info.update({
                "callback_query_id": update.callback_query.id,
                "user_id": update.callback_query.from_user.id,
                "data": update.callback_query.data,
                "message_id": update.callback_query.message.message_id if update.callback_query.message else None,
            })
        
        logger.info("Processing Telegram update", update_id=update.update_id, **update_info)
        
        # Process update through bot application
        try:
            # Ensure application is initialized/started (idempotent)
            try:
                await bot_application.initialize()
            except Exception:
                pass
            try:
                await bot_application.start()
            except Exception:
                pass
            await bot_application.process_update(update)
            
            logger.debug("Update processed successfully", update_id=update.update_id)
            
        except Exception as e:
            logger.error(
                "Failed to process update",
                update_id=update.update_id,
                error=str(e),
                exc_info=True
            )
            # Don't raise - return 200 to prevent Telegram from retrying
            # The error will be logged and handled internally
        
        # Always return 200 OK to acknowledge receipt
        return Response(status_code=200)
        
    except HTTPException:
        # Re-raise HTTP exceptions (auth errors, etc.)
        raise
        
    except Exception as e:
        logger.error("Webhook processing error", error=str(e), exc_info=True)
        # Return 200 to prevent Telegram retries on internal errors
        return Response(status_code=200)


@telegram_router.get("/webhook/info")
async def webhook_info() -> Dict[str, Any]:
    """
    Get webhook configuration information.
    
    Returns webhook status and configuration details.
    """
    try:
        # Get webhook info from Telegram
        webhook_info = await bot_application.bot.get_webhook_info()
        
        return {
            "webhook_configured": bool(settings.TELEGRAM_WEBHOOK_URL),
            "webhook_url": settings.TELEGRAM_WEBHOOK_URL,
            "secret_configured": bool(settings.TELEGRAM_WEBHOOK_SECRET),
            "telegram_webhook_info": {
                "url": webhook_info.url,
                "has_custom_certificate": webhook_info.has_custom_certificate,
                "pending_update_count": webhook_info.pending_update_count,
                "last_error_date": webhook_info.last_error_date.isoformat() if webhook_info.last_error_date else None,
                "last_error_message": webhook_info.last_error_message,
                "max_connections": webhook_info.max_connections,
                "allowed_updates": webhook_info.allowed_updates,
            }
        }
        
    except Exception as e:
        logger.error("Failed to get webhook info", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get webhook information"
        )


@telegram_router.post("/webhook/set")
async def set_webhook() -> Dict[str, str]:
    """
    Set up Telegram webhook (admin endpoint).
    
    This endpoint can be used to programmatically set up the webhook
    instead of doing it manually through initialize_bot().
    """
    try:
        if not settings.TELEGRAM_WEBHOOK_URL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TELEGRAM_WEBHOOK_URL not configured"
            )
        
        # Set webhook
        success = await bot_application.bot.set_webhook(
            url=settings.TELEGRAM_WEBHOOK_URL,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        
        if success:
            logger.info("Webhook set successfully", url=settings.TELEGRAM_WEBHOOK_URL)
            return {
                "status": "success",
                "message": "Webhook set successfully",
                "webhook_url": settings.TELEGRAM_WEBHOOK_URL,
            }
        else:
            logger.error("Failed to set webhook")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to set webhook"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error setting webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set webhook"
        )


@telegram_router.delete("/webhook")
async def delete_webhook() -> Dict[str, str]:
    """
    Delete Telegram webhook (admin endpoint).
    
    This will switch the bot back to polling mode.
    """
    try:
        success = await bot_application.bot.delete_webhook(drop_pending_updates=True)
        
        if success:
            logger.info("Webhook deleted successfully")
            return {
                "status": "success", 
                "message": "Webhook deleted successfully"
            }
        else:
            logger.error("Failed to delete webhook")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete webhook"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting webhook", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete webhook"
        )


# =============================================================================
# Development and Testing Endpoints
# =============================================================================

if settings.ENVIRONMENT == "development":
    
    @telegram_router.get("/webhook/test")
    async def test_webhook() -> Dict[str, str]:
        """Test endpoint to verify webhook router is working."""
        return {
            "status": "ok",
            "message": "Webhook router is working",
            "environment": settings.ENVIRONMENT,
        }
    
    @telegram_router.post("/webhook/simulate")
    async def simulate_update(update_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Simulate a Telegram update for testing (development only).
        
        Args:
            update_data: Raw update data as would be sent by Telegram
            
        Returns:
            Processing result
        """
        try:
            # Create Update object
            update = Update.de_json(update_data, bot_application.bot)
            if not update:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid update data"
                )
            
            # Process update
            await bot_application.process_update(update)
            
            logger.info("Simulated update processed", update_id=update.update_id)
            
            return {
                "status": "success",
                "message": f"Update {update.update_id} processed successfully",
            }
            
        except Exception as e:
            logger.error("Failed to simulate update", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process simulated update: {str(e)}"
            )


# =============================================================================
# Health Check
# =============================================================================

@telegram_router.get("/health")
async def webhook_health() -> Dict[str, Any]:
    """Webhook router health check."""
    try:
        # Test bot connection
        bot_info = await bot_application.bot.get_me()
        
        return {
            "status": "healthy",
            "bot_info": {
                "id": bot_info.id,
                "username": bot_info.username,
                "first_name": bot_info.first_name,
                "can_join_groups": bot_info.can_join_groups,
                "can_read_all_group_messages": bot_info.can_read_all_group_messages,
                "supports_inline_queries": bot_info.supports_inline_queries,
            },
            "webhook_configured": bool(settings.TELEGRAM_WEBHOOK_URL),
        }
        
    except Exception as e:
        logger.error("Webhook health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "webhook_configured": bool(settings.TELEGRAM_WEBHOOK_URL),
        }


# =============================================================================
# Export
# =============================================================================

__all__ = ["telegram_router"]
