"""
Database Models and ORM Setup
מודלים ובסיס נתונים של המערכת

This module contains all database models using SQLAlchemy 2.0 with async support.
Models follow the event-driven architecture with audit trails and optimized for
GIS operations.
"""

import enum
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import settings
import structlog

logger = structlog.get_logger(__name__).bind(component="database")

# =============================================================================
# Enums for Type Safety
# =============================================================================

class UserRole(str, enum.Enum):
    """User role enumeration."""
    REPORTER = "reporter"          # Regular user reporting animals
    ORG_STAFF = "org_staff"       # Organization staff member
    ORG_ADMIN = "org_admin"       # Organization administrator
    SYSTEM_ADMIN = "system_admin" # System administrator


class ReportStatus(str, enum.Enum):
    """Report status lifecycle."""
    DRAFT = "draft"               # Being created by user
    SUBMITTED = "submitted"       # Submitted by user
    PENDING = "pending"           # Waiting for organization response
    ACKNOWLEDGED = "acknowledged" # Organization acknowledged receipt
    IN_PROGRESS = "in_progress"   # Organization is handling
    RESOLVED = "resolved"         # Successfully resolved
    CLOSED = "closed"             # Closed without resolution
    DUPLICATE = "duplicate"       # Marked as duplicate
    INVALID = "invalid"           # Invalid/spam report


class AnimalType(str, enum.Enum):
    """Animal type categories."""
    DOG = "dog"
    CAT = "cat"
    BIRD = "bird"
    WILDLIFE = "wildlife"
    EXOTIC = "exotic"
    LIVESTOCK = "livestock"
    OTHER = "other"
    UNKNOWN = "unknown"


class UrgencyLevel(str, enum.Enum):
    """Urgency classification levels."""
    LOW = "low"                   # Not urgent, can wait
    MEDIUM = "medium"             # Should be handled soon
    HIGH = "high"                 # Urgent, needs quick response
    CRITICAL = "critical"         # Life-threatening emergency


class OrganizationType(str, enum.Enum):
    """Organization type categories."""
    VET_CLINIC = "vet_clinic"           # Veterinary clinic
    EMERGENCY_VET = "emergency_vet"     # 24/7 emergency veterinary
    ANIMAL_HOSPITAL = "animal_hospital" # Large veterinary hospital
    ANIMAL_SHELTER = "animal_shelter"   # Animal shelter/pound
    RESCUE_ORG = "rescue_org"           # Animal rescue organization
    GOVERNMENT = "government"           # Municipal services
    VOLUNTEER_GROUP = "volunteer_group" # Volunteer group


class AlertChannel(str, enum.Enum):
    """Alert delivery channels."""
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    WEBHOOK = "webhook"


class AlertStatus(str, enum.Enum):
    """Alert delivery status."""
    QUEUED = "queued"       # Waiting to be sent
    SENDING = "sending"     # Currently being sent
    SENT = "sent"           # Successfully sent
    DELIVERED = "delivered" # Confirmed delivery
    FAILED = "failed"       # Failed to send
    REJECTED = "rejected"   # Rejected by recipient


class FileType(str, enum.Enum):
    """File type categories."""
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


class EventType(str, enum.Enum):
    """Event types for audit trail."""
    REPORT_CREATED = "report_created"
    REPORT_UPDATED = "report_updated"
    REPORT_STATUS_CHANGED = "report_status_changed"
    ALERT_SENT = "alert_sent"
    ORGANIZATION_RESPONDED = "organization_responded"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    SYSTEM_EVENT = "system_event"


# =============================================================================
# Base Model with Common Fields
# =============================================================================

class Base(AsyncAttrs, DeclarativeBase):
    """
    Base class for all database models.
    
    Provides common fields and functionality:
    - UUID primary keys
    - Created/updated timestamps
    - Async support via AsyncAttrs
    """
    
    # Type mapping for datetime with timezone support
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict: JSONB,
        Dict: JSONB,
        list: JSONB,
        List: JSONB,
    }


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Record creation timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Last update timestamp"
    )


class UUIDMixin:
    """Mixin for UUID primary keys."""
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        doc="Primary key UUID"
    )


# =============================================================================
# User Management Models
# =============================================================================

class User(Base, UUIDMixin, TimestampMixin):
    """
    User model for authentication and authorization.
    
    Supports different user types: reporters, organization staff, admins.
    """
    
    __tablename__ = "users"
    
    # Basic user information
    telegram_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        unique=True,
        nullable=True,
        doc="Telegram user ID for bot integration"
    )
    
    username: Mapped[Optional[str]] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
        doc="Username (optional)"
    )
    
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        doc="Email address"
    )
    
    phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Phone number"
    )
    
    # Display information
    full_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Full display name"
    )
    
    # Role and permissions
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        default=UserRole.REPORTER,
        nullable=False,
        doc="User role and permissions"
    )
    
    # User preferences
    language: Mapped[str] = mapped_column(
        String(5),
        default="he",
        nullable=False,
        doc="Preferred language (ISO 639-1)"
    )
    
    timezone: Mapped[str] = mapped_column(
        String(50),
        default="Asia/Jerusalem",
        nullable=False,
        doc="User timezone"
    )
    
    # Status and verification
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Whether user account is active"
    )
    
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether user identity is verified"
    )
    
    # Trust system
    trust_score: Mapped[float] = mapped_column(
        Float,
        default=5.0,
        nullable=False,
        doc="User trust score (0-10)"
    )
    
    # Statistics
    reports_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total reports submitted by user"
    )
    
    successful_reports_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Successfully resolved reports"
    )
    
    # Authentication
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last login timestamp"
    )
    
    # Organization membership (for org staff)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated organization (for staff)"
    )
    
    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", 
        back_populates="staff_members",
        foreign_keys=[organization_id]
    )
    
    reports: Mapped[List["Report"]] = relationship(
        "Report", 
        back_populates="reporter"
    )
    
    # Table constraints
    __table_args__ = (
        CheckConstraint(
            "trust_score >= 0.0 AND trust_score <= 10.0",
            name="check_trust_score_range"
        ),
        CheckConstraint(
            "reports_count >= 0",
            name="check_reports_count_positive"
        ),
        CheckConstraint(
            "successful_reports_count >= 0",
            name="check_successful_reports_count_positive"
        ),
        CheckConstraint(
            "successful_reports_count <= reports_count",
            name="check_successful_reports_not_exceed_total"
        ),
        Index("ix_users_telegram_user_id", "telegram_user_id"),
        Index("ix_users_email", "email"),
        Index("ix_users_role", "role"),
        Index("ix_users_organization_id", "organization_id"),
        Index("ix_users_trust_score", "trust_score"),
    )


# =============================================================================
# Organization Management Models
# =============================================================================

class Organization(Base, UUIDMixin, TimestampMixin):
    """
    Organization model for veterinary clinics, shelters, rescue groups, etc.
    
    Includes geographic information for proximity searches.
    """
    
    __tablename__ = "organizations"
    
    # Basic information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Organization name"
    )
    
    name_en: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="English name"
    )
    
    name_ar: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Arabic name"
    )
    
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Organization description"
    )
    
    # Type and specialization
    organization_type: Mapped[OrganizationType] = mapped_column(
        Enum(OrganizationType),
        nullable=False,
        doc="Type of organization"
    )
    
    specialties: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default=list,
        doc="Animal specialties (e.g., ['dogs', 'cats', 'birds'])"
    )
    
    # Contact information
    primary_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Primary phone number"
    )
    
    emergency_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="24/7 emergency phone"
    )
    
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Email address"
    )
    
    website: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Website URL"
    )
    
    # Geographic information
    address: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Full address"
    )
    
    city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="City name"
    )
    
    # GIS coordinates for proximity search
    location: Mapped[Optional[str]] = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True,
        doc="Geographic coordinates (PostGIS Point)"
    )
    
    # For applications without PostGIS support
    latitude: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Latitude coordinate"
    )
    
    longitude: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Longitude coordinate"
    )
    
    # Service area radius in kilometers
    service_radius_km: Mapped[float] = mapped_column(
        Float,
        default=10.0,
        nullable=False,
        doc="Service area radius in kilometers"
    )
    
    # Operating information
    is_24_7: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Operates 24/7"
    )
    
    operating_hours: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Operating hours by day of week"
    )
    
    # Status and verification
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Organization is active"
    )
    
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Organization identity verified"
    )
    
    # Integration with external systems
    google_place_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        doc="Google Places API place ID"
    )
    
    # Response statistics
    average_response_time_minutes: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Average response time in minutes"
    )
    
    total_reports_handled: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total reports handled"
    )
    
    successful_rescues: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of successful rescues"
    )
    
    # Alert preferences
    alert_channels: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default=["telegram", "email"],
        doc="Preferred alert channels"
    )
    
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Telegram chat ID for alerts"
    )
    
    # Relationships
    staff_members: Mapped[List["User"]] = relationship(
        "User",
        back_populates="organization",
        foreign_keys="User.organization_id"
    )
    
    alerts_received: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="organization"
    )
    
    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "service_radius_km > 0",
            name="check_service_radius_positive"
        ),
        CheckConstraint(
            "total_reports_handled >= 0",
            name="check_total_reports_positive"
        ),
        CheckConstraint(
            "successful_rescues >= 0",
            name="check_successful_rescues_positive"
        ),
        CheckConstraint(
            "successful_rescues <= total_reports_handled",
            name="check_successful_not_exceed_total"
        ),
        Index("ix_organizations_location", "location", postgresql_using="gist"),
        Index("ix_organizations_lat_lon", "latitude", "longitude"),
        Index("ix_organizations_city", "city"),
        Index("ix_organizations_type", "organization_type"),
        Index("ix_organizations_is_active", "is_active"),
        Index("ix_organizations_is_24_7", "is_24_7"),
        Index("ix_organizations_google_place_id", "google_place_id"),
    )


# =============================================================================
# Report and Incident Models
# =============================================================================

class Report(Base, UUIDMixin, TimestampMixin):
    """
    Main report model for animal incidents.
    
    Core entity that tracks animal rescue/assistance requests from submission
    to resolution.
    """
    
    __tablename__ = "reports"
    
    # Reporter information
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who submitted the report"
    )
    
    # Basic incident information
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Brief report title"
    )
    
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Detailed description of the situation"
    )
    
    # Classification
    animal_type: Mapped[AnimalType] = mapped_column(
        Enum(AnimalType),
        default=AnimalType.UNKNOWN,
        nullable=False,
        doc="Type of animal involved"
    )
    
    urgency_level: Mapped[UrgencyLevel] = mapped_column(
        Enum(UrgencyLevel),
        default=UrgencyLevel.MEDIUM,
        nullable=False,
        doc="Urgency classification"
    )
    
    # Status tracking
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus),
        default=ReportStatus.SUBMITTED,
        nullable=False,
        doc="Current report status"
    )
    
    # Geographic information
    location: Mapped[Optional[str]] = mapped_column(
        Geometry("POINT", srid=4326),
        nullable=True,
        doc="Incident location (PostGIS Point)"
    )
    
    latitude: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Incident latitude"
    )
    
    longitude: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Incident longitude"
    )
    
    address: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Human-readable address"
    )
    
    city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="City where incident occurred"
    )
    
    # Location confidence and validation
    location_accuracy_meters: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="GPS accuracy in meters"
    )
    
    address_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Address verified by geocoding"
    )
    
    # Additional metadata
    language: Mapped[str] = mapped_column(
        String(5),
        default="he",
        nullable=False,
        doc="Language of report content"
    )
    
    # NLP analysis results
    keywords: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        default=list,
        doc="Extracted keywords from description"
    )
    
    sentiment_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Sentiment analysis score (-1 to 1)"
    )
    
    # Duplicates and similarity
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Marked as duplicate"
    )
    
    duplicate_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="SET NULL"),
        nullable=True,
        doc="Original report if this is a duplicate"
    )
    
    # Response tracking
    first_response_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="First organization response time"
    )
    
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Resolution timestamp"
    )
    
    assigned_organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        doc="Organization handling the case"
    )
    
    # Public identifier for sharing
    public_id: Mapped[str] = mapped_column(
        String(12),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())[:8].upper(),
        doc="Short public identifier"
    )
    
    # Expiry and cleanup
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Report expiration time"
    )
    
    # Relationships
    reporter: Mapped["User"] = relationship(
        "User",
        back_populates="reports"
    )
    
    assigned_organization: Mapped[Optional["Organization"]] = relationship(
        "Organization",
        foreign_keys=[assigned_organization_id]
    )
    
    files: Mapped[List["ReportFile"]] = relationship(
        "ReportFile",
        back_populates="report",
        cascade="all, delete-orphan"
    )
    
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert",
        back_populates="report",
        cascade="all, delete-orphan"
    )
    
    duplicate_of: Mapped[Optional["Report"]] = relationship(
        "Report",
        remote_side="Report.id",
        foreign_keys=[duplicate_of_id]
    )
    
    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "sentiment_score IS NULL OR (sentiment_score >= -1.0 AND sentiment_score <= 1.0)",
            name="check_sentiment_score_range"
        ),
        CheckConstraint(
            "location_accuracy_meters IS NULL OR location_accuracy_meters >= 0",
            name="check_location_accuracy_positive"
        ),
        Index("ix_reports_location", "location", postgresql_using="gist"),
        Index("ix_reports_lat_lon", "latitude", "longitude"),
        Index("ix_reports_reporter_id", "reporter_id"),
        Index("ix_reports_status", "status"),
        Index("ix_reports_urgency_level", "urgency_level"),
        Index("ix_reports_animal_type", "animal_type"),
        Index("ix_reports_city", "city"),
        Index("ix_reports_public_id", "public_id"),
        Index("ix_reports_created_at", "created_at"),
        Index("ix_reports_assigned_organization_id", "assigned_organization_id"),
        Index("ix_reports_is_duplicate", "is_duplicate"),
    )


# =============================================================================
# File Attachments
# =============================================================================

class ReportFile(Base, UUIDMixin, TimestampMixin):
    """
    File attachments for reports (photos, videos, documents).
    """
    
    __tablename__ = "report_files"
    
    # Parent report
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        doc="Associated report"
    )
    
    # File metadata
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original filename"
    )
    
    file_type: Mapped[FileType] = mapped_column(
        Enum(FileType),
        nullable=False,
        doc="Type of file"
    )
    
    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="MIME type"
    )
    
    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="File size in bytes"
    )
    
    # Storage information
    storage_backend: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Storage backend (local, s3, r2)"
    )
    
    storage_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Path to file in storage"
    )
    
    storage_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        doc="Public URL for file access"
    )
    
    # Image/video specific metadata
    width: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Image/video width in pixels"
    )
    
    height: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Image/video height in pixels"
    )
    
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Video/audio duration in seconds"
    )
    
    # File integrity
    file_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA-256 hash for deduplication"
    )
    
    # Processing status
    is_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="File has been processed"
    )
    
    is_thumbnail_generated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Thumbnail has been generated"
    )
    
    # Relationships
    report: Mapped["Report"] = relationship(
        "Report",
        back_populates="files"
    )
    
    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "file_size_bytes > 0",
            name="check_file_size_positive"
        ),
        CheckConstraint(
            "width IS NULL OR width > 0",
            name="check_width_positive"
        ),
        CheckConstraint(
            "height IS NULL OR height > 0",
            name="check_height_positive"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="check_duration_non_negative"
        ),
        Index("ix_report_files_report_id", "report_id"),
        Index("ix_report_files_file_type", "file_type"),
        Index("ix_report_files_file_hash", "file_hash"),
        Index("ix_report_files_storage_backend", "storage_backend"),
    )


# =============================================================================
# Alert and Notification System
# =============================================================================

class Alert(Base, UUIDMixin, TimestampMixin):
    """
    Alert/notification model for notifying organizations about reports.
    """
    
    __tablename__ = "alerts"
    
    # Associated entities
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        doc="Report that triggered the alert"
    )
    
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Target organization"
    )
    
    # Alert configuration
    channel: Mapped[AlertChannel] = mapped_column(
        Enum(AlertChannel),
        nullable=False,
        doc="Delivery channel"
    )
    
    recipient: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Recipient identifier (email, phone, chat_id)"
    )
    
    # Content
    subject: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Alert subject/title"
    )
    
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Alert message content"
    )
    
    message_template: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Template used for message generation"
    )
    
    # Delivery tracking
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus),
        default=AlertStatus.QUEUED,
        nullable=False,
        doc="Alert delivery status"
    )
    
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When alert should be sent"
    )
    
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When alert was actually sent"
    )
    
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When delivery was confirmed"
    )
    
    # Retry logic
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of delivery attempts"
    )
    
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
        doc="Maximum number of attempts"
    )
    
    retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Next retry time"
    )
    
    # Error handling
    last_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Last error message"
    )
    
    # External system references
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="External system message ID"
    )
    
    # Response tracking
    response_received: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Organization has responded to alert"
    )
    
    response_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When organization response was received"
    )
    
    # Relationships
    report: Mapped["Report"] = relationship(
        "Report",
        back_populates="alerts"
    )
    
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="alerts_received"
    )
    
    # Table constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "attempts >= 0",
            name="check_attempts_non_negative"
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="check_max_attempts_positive"
        ),
        CheckConstraint(
            "attempts <= max_attempts",
            name="check_attempts_not_exceed_max"
        ),
        Index("ix_alerts_report_id", "report_id"),
        Index("ix_alerts_organization_id", "organization_id"),
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_channel", "channel"),
        Index("ix_alerts_scheduled_at", "scheduled_at"),
        Index("ix_alerts_retry_at", "retry_at"),
        Index("ix_alerts_external_id", "external_id"),
        UniqueConstraint(
            "report_id", "organization_id", "channel",
            name="uq_alert_report_org_channel"
        ),
    )


# =============================================================================
# Audit Trail and Events
# =============================================================================

class Event(Base, UUIDMixin, TimestampMixin):
    """
    Event log for audit trail and system monitoring.
    
    Part of the event-driven architecture and outbox pattern.
    """
    
    __tablename__ = "events"
    
    # Event classification
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType),
        nullable=False,
        doc="Type of event"
    )
    
    # Entity references
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type of entity (report, user, organization)"
    )
    
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        doc="ID of affected entity"
    )
    
    # Event data
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        doc="Event payload data"
    )
    
    # Context
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who triggered the event"
    )
    
    # Processing status (for outbox pattern)
    processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Event has been processed"
    )
    
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When event was processed"
    )
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[user_id]
    )
    
    # Table constraints and indexes
    __table_args__ = (
        Index("ix_events_event_type", "event_type"),
        Index("ix_events_entity_type_id", "entity_type", "entity_id"),
        Index("ix_events_user_id", "user_id"),
        Index("ix_events_processed", "processed"),
        Index("ix_events_created_at", "created_at"),
    )


# =============================================================================
# Database Engine and Session Management
# =============================================================================

# Create async engine with optimized settings
engine = create_async_engine(
    str(settings.DATABASE_URL),
    **settings.DATABASE_ENGINE_OPTIONS,
)

# Create session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
    autocommit=False,
)


# =============================================================================
# Database Session Dependency
# =============================================================================

async def get_db_session() -> AsyncSession:
    """
    Get async database session.
    
    This function provides a database session for dependency injection
    in FastAPI endpoints.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# =============================================================================
# Database Initialization
# =============================================================================

async def create_tables() -> None:
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def wait_for_database(
    max_attempts: int = 10,
    initial_delay_seconds: float = 0.5,
    max_delay_seconds: float = 5.0,
) -> None:
    """Wait for database to become available with exponential backoff.

    Raises last exception if database is not reachable after all attempts.
    """
    attempt = 0
    delay = float(initial_delay_seconds)
    last_error: Optional[Exception] = None

    while attempt < max_attempts:
        try:
            async with async_session_maker() as session:
                # Lightweight connectivity check
                await session.execute(text("SELECT 1"))
            if attempt > 0:
                logger.info(
                    "Database became available",
                    attempts=attempt + 1,
                )
            return
        except Exception as exc:  # noqa: BLE001 - we want original error
            last_error = exc
            logger.warning(
                "Database not reachable yet",
                attempt=attempt + 1,
                delay_seconds=delay,
                error=str(exc),
            )
            await asyncio.sleep(delay)
            delay = min(max_delay_seconds, delay * 2)
            attempt += 1

    logger.error(
        "Database not reachable after retries",
        attempts=max_attempts,
        error=str(last_error) if last_error else None,
    )
    if last_error:
        raise last_error


async def drop_tables() -> None:
    """Drop all database tables (use with caution!)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# =============================================================================
# Database Utilities
# =============================================================================

def create_point_from_coordinates(latitude: float, longitude: float) -> str:
    """
    Create PostGIS POINT from coordinates.
    
    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        
    Returns:
        WKT POINT string for PostGIS
    """
    return f"POINT({longitude} {latitude})"


def calculate_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Calculate distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        
    Returns:
        Distance in kilometers
    """
    from math import radians, sin, cos, sqrt, atan2
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    # Earth's radius in kilometers
    return 6371 * c


# =============================================================================
# Health Check Queries
# =============================================================================

async def check_database_health() -> Dict[str, Any]:
    """Check database connectivity and performance."""
    try:
        async with async_session_maker() as session:
            # Test basic connectivity
            result = await session.execute(text("SELECT 1 as test"))
            test_value = result.scalar()
            
            # Test table access
            user_count = await session.execute(text("SELECT COUNT(*) FROM users"))
            users_total = user_count.scalar()
            
            # Test recent activity
            recent_reports = await session.execute(
                text("SELECT COUNT(*) FROM reports WHERE created_at > NOW() - INTERVAL '24 hours'")
            )
            reports_today = recent_reports.scalar()
            
            return {
                "status": "healthy",
                "test_query": test_value == 1,
                "users_total": users_total,
                "reports_today": reports_today,
                "engine_pool_size": engine.pool.size(),
                "engine_pool_checked_in": engine.pool.checkedin(),
                "engine_pool_checked_out": engine.pool.checkedout(),
            }
            
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


# =============================================================================
# Export Models for Alembic
# =============================================================================

# Make all models available for Alembic auto-generation
__all__ = [
    "Base",
    "User",
    "Organization", 
    "Report",
    "ReportFile",
    "Alert",
    "Event",
    "engine",
    "async_session_maker",
    "get_db_session",
    "create_tables",
    "drop_tables",
    "check_database_health",
]
