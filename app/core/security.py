"""
Security and Authentication Module
מודול אבטחה ואימות

This module provides authentication, authorization and security utilities
for the Animal Rescue Bot system including JWT tokens, password hashing,
and role-based access control.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import get_db_session, User, UserRole
from app.core.exceptions import PermissionDeniedError, ValidationError

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# Security Configuration
# =============================================================================

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days for mobile app convenience

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)

# =============================================================================
# Password Operations
# =============================================================================

def create_password_hash(password: str) -> str:
    """
    Create password hash using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hash.
    
    Args:
        plain_password: Plain text password to check
        hashed_password: Stored password hash
        
    Returns:
        True if password matches
    """
    return pwd_context.verify(plain_password, hashed_password)


# =============================================================================
# JWT Token Operations
# =============================================================================

def create_access_token(
    subject: Union[str, int], 
    expires_delta: Optional[timedelta] = None,
    additional_claims: Optional[Dict[str, Any]] = None
) -> str:
    """
    Create JWT access token.
    
    Args:
        subject: Token subject (user ID)
        expires_delta: Token expiration time delta
        additional_claims: Additional claims to include
        
    Returns:
        JWT token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    
    if additional_claims:
        to_encode.update(additional_claims)
    
    try:
        encoded_jwt = jwt.encode(
            to_encode, 
            settings.SECRET_KEY, 
            algorithm=ALGORITHM
        )
        return encoded_jwt
    except Exception as e:
        logger.error("Failed to create access token", error=str(e))
        raise ValidationError("Failed to create access token")


def create_telegram_auth_token(user_id: uuid.UUID, telegram_user_id: int) -> str:
    """
    Create special JWT token for Telegram bot authentication.
    
    Args:
        user_id: Database user ID
        telegram_user_id: Telegram user ID
        
    Returns:
        JWT token string for Telegram authentication
    """
    expire = datetime.now(timezone.utc) + timedelta(days=30)  # Longer for bots
    
    to_encode = {
        "exp": expire,
        "sub": str(user_id),
        "telegram_user_id": telegram_user_id,
        "iat": datetime.now(timezone.utc),
        "type": "telegram",
    }
    
    try:
        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm=ALGORITHM
        )
        return encoded_jwt
    except Exception as e:
        logger.error("Failed to create Telegram auth token", error=str(e))
        raise ValidationError("Failed to create Telegram auth token")


def decode_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload
        
    Raises:
        ValidationError: If token is invalid
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[ALGORITHM]
        )
        
        # Validate required fields
        if not payload.get("sub"):
            raise ValidationError("Token missing subject")
        
        # Check expiration manually for better error handling
        exp = payload.get("exp")
        if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
            raise ValidationError("Token has expired")
        
        return payload
        
    except jwt.PyJWTError as e:
        logger.debug("JWT decode error", error=str(e))
        raise ValidationError("Invalid token")
    except Exception as e:
        logger.error("Token decode error", error=str(e))
        raise ValidationError("Token validation failed")


# =============================================================================
# User Authentication Dependencies
# =============================================================================

async def get_current_user(
    session: AsyncSession = Depends(get_db_session),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[User]:
    """
    Get current authenticated user from JWT token.
    
    This is an optional dependency - returns None if no valid token provided.
    Use require_authentication() for mandatory authentication.
    
    Args:
        session: Database session
        credentials: HTTP Authorization credentials
        
    Returns:
        User instance or None if not authenticated
    """
    if not credentials:
        return None
    
    try:
        # Decode token
        payload = decode_token(credentials.credentials)
        user_id = payload.get("sub")
        
        if not user_id:
            return None
        
        # Get user from database
        result = await session.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            return None
        
        # Update last activity
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        
        logger.debug("User authenticated", user_id=str(user.id), role=user.role.value)
        return user
        
    except Exception as e:
        logger.debug("Authentication failed", error=str(e))
        return None


async def require_authentication(
    session: AsyncSession = Depends(get_db_session),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """
    Require valid authentication - raises 401 if not authenticated.
    
    Args:
        session: Database session
        credentials: HTTP Authorization credentials
        
    Returns:
        Authenticated User instance
        
    Raises:
        HTTPException: 401 if not authenticated
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = decode_token(credentials.credentials)
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        
        # Get user from database
        result = await session.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is disabled",
            )
        
        # Update last activity
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        
        return user
        
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    except Exception as e:
        logger.error("Authentication error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
        )


# =============================================================================
# Telegram Bot Authentication
# =============================================================================

async def authenticate_telegram_user(
    telegram_user_id: int,
    session: AsyncSession
) -> Optional[User]:
    """
    Authenticate Telegram user and return database user.
    
    Args:
        telegram_user_id: Telegram user ID
        session: Database session
        
    Returns:
        User instance or None if not found
    """
    try:
        result = await session.execute(
            select(User).where(
                User.telegram_user_id == telegram_user_id,
                User.is_active == True
            )
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update last activity
            user.last_login_at = datetime.now(timezone.utc)
            await session.commit()
            
            logger.debug("Telegram user authenticated", 
                        telegram_id=telegram_user_id, 
                        user_id=str(user.id))
        
        return user
        
    except Exception as e:
        logger.error("Telegram authentication error", error=str(e))
        return None


# =============================================================================
# Role-Based Access Control
# =============================================================================

def require_roles(allowed_roles: List[UserRole]):
    """
    Create dependency that requires specific user roles.
    
    Args:
        allowed_roles: List of allowed user roles
        
    Returns:
        FastAPI dependency function
    """
    async def role_checker(
        current_user: User = Depends(require_authentication)
    ) -> User:
        """Check if user has required role."""
        if current_user.role not in allowed_roles:
            logger.warning(
                "Access denied - insufficient role",
                user_id=str(current_user.id),
                user_role=current_user.role.value,
                required_roles=[role.value for role in allowed_roles]
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[role.value for role in allowed_roles]}",
            )
        
        return current_user
    
    return role_checker


def require_admin():
    """Shortcut dependency for admin access."""
    return require_roles([UserRole.SYSTEM_ADMIN])


def require_org_staff():
    """Shortcut dependency for organization staff access."""
    return require_roles([
        UserRole.ORG_STAFF, 
        UserRole.ORG_ADMIN, 
        UserRole.SYSTEM_ADMIN
    ])


# =============================================================================
# Permission Checkers
# =============================================================================

def can_access_report(user: User, report) -> bool:
    """
    Check if user can access a specific report.
    
    Args:
        user: User instance
        report: Report instance
        
    Returns:
        True if user can access the report
    """
    # System admin can access everything
    if user.role == UserRole.SYSTEM_ADMIN:
        return True
    
    # Reporter can access their own reports
    if report.reporter_id == user.id:
        return True
    
    # Organization staff can access reports assigned to their organization
    if (user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN] and
        user.organization_id and
        report.assigned_organization_id == user.organization_id):
        return True
    
    return False


def can_modify_report(user: User, report) -> bool:
    """
    Check if user can modify a specific report.
    
    Args:
        user: User instance
        report: Report instance
        
    Returns:
        True if user can modify the report
    """
    # System admin can modify everything
    if user.role == UserRole.SYSTEM_ADMIN:
        return True
    
    # Reporter can modify their own reports (if not resolved)
    if (report.reporter_id == user.id and 
        report.status not in ["resolved", "closed"]):
        return True
    
    # Organization admins can modify reports assigned to their organization
    if (user.role == UserRole.ORG_ADMIN and
        user.organization_id and
        report.assigned_organization_id == user.organization_id):
        return True
    
    return False


def can_manage_organization(user: User, organization_id: uuid.UUID) -> bool:
    """
    Check if user can manage a specific organization.
    
    Args:
        user: User instance
        organization_id: Organization UUID
        
    Returns:
        True if user can manage the organization
    """
    # System admin can manage all organizations
    if user.role == UserRole.SYSTEM_ADMIN:
        return True
    
    # Organization admin can manage their own organization
    if (user.role == UserRole.ORG_ADMIN and
        user.organization_id == organization_id):
        return True
    
    return False


# =============================================================================
# Security Headers and Middleware
# =============================================================================

def get_security_headers() -> Dict[str, str]:
    """Get security headers for responses."""
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }


# =============================================================================
# Request Validation
# =============================================================================

def validate_request_source(request: Request) -> bool:
    """
    Validate request source for additional security.
    
    Args:
        request: FastAPI request object
        
    Returns:
        True if request source is valid
    """
    # In production, add checks for:
    # - Allowed IP ranges
    # - User-Agent validation
    # - Rate limiting per IP
    # - CSRF token validation
    
    # For development, allow all
    if settings.ENVIRONMENT == "development":
        return True
    
    # TODO: Implement production security checks
    return True


# =============================================================================
# Export Public Interface
# =============================================================================

__all__ = [
    # Password functions
    "create_password_hash",
    "verify_password",
    
    # JWT functions
    "create_access_token", 
    "create_telegram_auth_token",
    "decode_token",
    
    # Authentication dependencies
    "get_current_user",
    "require_authentication", 
    "authenticate_telegram_user",
    
    # Authorization dependencies
    "require_roles",
    "require_admin",
    "require_org_staff",
    
    # Permission checkers
    "can_access_report",
    "can_modify_report", 
    "can_manage_organization",
    
    # Security utilities
    "get_security_headers",
    "validate_request_source",
]
