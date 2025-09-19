"""
Reports API Endpoints
נקודות קצה API לדיווחים

This module provides REST API endpoints for report management in the Animal Rescue Bot.
Includes CRUD operations, search, filtering, and status updates for reports.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, and_, or_, desc, asc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.rate_limit import check_rate_limit, RateLimitExceeded
from app.core.security import get_current_user, require_roles
from app.models.database import (
    get_db_session, User, Report, ReportFile, Organization, Alert,
    ReportStatus, UrgencyLevel, AnimalType, UserRole, AlertStatus
)
from app.services.file_storage import FileStorageService
from app.services.geocoding import GeocodingService
from app.services.nlp import NLPService
from app.workers.jobs import process_new_report, send_organization_alert
from app.core.exceptions import NotFoundError, ValidationError, PermissionDeniedError

# =============================================================================
# Logger and Services
# =============================================================================

logger = structlog.get_logger(__name__)
router = APIRouter()

file_storage = FileStorageService()
geocoding_service = GeocodingService()
nlp_service = NLPService()

# =============================================================================
# Request/Response Models
# =============================================================================

class LocationModel(BaseModel):
    """Location data model."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: Optional[str] = None
    city: Optional[str] = None
    accuracy_meters: Optional[float] = Field(None, ge=0)


class ReportCreateRequest(BaseModel):
    """Request model for creating a new report."""
    title: str = Field(..., min_length=10, max_length=255)
    description: str = Field(..., min_length=20, max_length=2000)
    animal_type: AnimalType
    urgency_level: UrgencyLevel
    location: LocationModel
    language: str = Field(default="he", regex="^(he|ar|en)$")
    
    @validator("description")
    def validate_description(cls, v):
        """Validate description content."""
        if len(v.strip()) < 20:
            raise ValueError("Description must be at least 20 characters")
        return v.strip()


class ReportUpdateRequest(BaseModel):
    """Request model for updating a report."""
    title: Optional[str] = Field(None, min_length=10, max_length=255)
    description: Optional[str] = Field(None, min_length=20, max_length=2000)
    animal_type: Optional[AnimalType] = None
    urgency_level: Optional[UrgencyLevel] = None
    status: Optional[ReportStatus] = None


class ReportFileResponse(BaseModel):
    """Response model for report files."""
    id: str
    filename: str
    file_type: str
    mime_type: str
    file_size_bytes: int
    width: Optional[int]
    height: Optional[int]
    storage_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AlertResponse(BaseModel):
    """Response model for alerts."""
    id: str
    organization_id: str
    organization_name: str
    channel: str
    status: str
    sent_at: Optional[datetime]
    response_received: bool

    class Config:
        from_attributes = True


class ReportResponse(BaseModel):
    """Response model for reports."""
    id: str
    public_id: str
    title: str
    description: str
    animal_type: str
    urgency_level: str
    status: str
    language: str
    
    # Location data
    latitude: Optional[float]
    longitude: Optional[float]
    address: Optional[str]
    city: Optional[str]
    location_accuracy_meters: Optional[float]
    address_verified: bool
    
    # Metadata
    keywords: List[str]
    sentiment_score: Optional[float]
    is_duplicate: bool
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    first_response_at: Optional[datetime]
    resolved_at: Optional[datetime]
    
    # Reporter info (limited)
    reporter_name: Optional[str]
    
    # Related data
    files: List[ReportFileResponse]
    alerts: List[AlertResponse]
    
    # Statistics
    total_alerts: int
    successful_alerts: int

    class Config:
        from_attributes = True


class ReportListResponse(BaseModel):
    """Response model for paginated report lists."""
    reports: List[ReportResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class ReportSearchParams(BaseModel):
    """Search parameters for reports."""
    query: Optional[str] = Field(None, max_length=100)
    animal_type: Optional[AnimalType] = None
    urgency_level: Optional[UrgencyLevel] = None
    status: Optional[ReportStatus] = None
    city: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, regex="^(he|ar|en)$")
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_km: Optional[float] = Field(None, ge=1, le=100)
    
    # Sorting
    sort_by: str = Field(default="created_at", regex="^(created_at|urgency_level|status|city)$")
    sort_order: str = Field(default="desc", regex="^(asc|desc)$")
    
    # Pagination
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# =============================================================================
# Utility Functions
# =============================================================================

async def get_report_by_id_or_public_id(
    identifier: str, 
    session: AsyncSession,
    user: Optional[User] = None,
    require_owner: bool = False
) -> Report:
    """
    Get report by ID or public ID with proper access control.
    
    Args:
        identifier: Report ID (UUID) or public ID
        session: Database session
        user: Current user (for access control)
        require_owner: Whether to require user to be the report owner
        
    Returns:
        Report instance
        
    Raises:
        NotFoundError: If report not found or access denied
    """
    try:
        # Try UUID first
        report_id = uuid.UUID(identifier)
        query = select(Report).where(Report.id == report_id)
    except ValueError:
        # Use public ID
        query = select(Report).where(Report.public_id == identifier.upper())
    
    # Add eager loading
    query = query.options(
        selectinload(Report.reporter),
        selectinload(Report.files),
        selectinload(Report.alerts).selectinload(Alert.organization),
        selectinload(Report.assigned_organization)
    )
    
    result = await session.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise NotFoundError(f"Report {identifier} not found")
    
    # Access control
    if user:
        if require_owner and report.reporter_id != user.id:
            raise PermissionDeniedError("You can only access your own reports")
        
        # Organization staff can see reports assigned to them
        if (user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN] and 
            user.organization_id and 
            report.assigned_organization_id != user.organization_id):
            raise PermissionDeniedError("You can only access reports assigned to your organization")
    
    return report


def format_report_response(report: Report) -> Dict[str, Any]:
    """Format report data for API response."""
    
    # Count alerts
    total_alerts = len(report.alerts)
    successful_alerts = len([a for a in report.alerts if a.status == AlertStatus.SENT])
    
    # Format files
    files = []
    for file in report.files:
        files.append({
            "id": str(file.id),
            "filename": file.filename,
            "file_type": file.file_type.value,
            "mime_type": file.mime_type,
            "file_size_bytes": file.file_size_bytes,
            "width": file.width,
            "height": file.height,
            "storage_url": file.storage_url,
            "created_at": file.created_at,
        })
    
    # Format alerts
    alerts = []
    for alert in report.alerts:
        alerts.append({
            "id": str(alert.id),
            "organization_id": str(alert.organization_id),
            "organization_name": alert.organization.name if alert.organization else "Unknown",
            "channel": alert.channel.value,
            "status": alert.status.value,
            "sent_at": alert.sent_at,
            "response_received": alert.response_received,
        })
    
    return {
        "id": str(report.id),
        "public_id": report.public_id,
        "title": report.title,
        "description": report.description,
        "animal_type": report.animal_type.value,
        "urgency_level": report.urgency_level.value,
        "status": report.status.value,
        "language": report.language,
        
        # Location
        "latitude": report.latitude,
        "longitude": report.longitude,
        "address": report.address,
        "city": report.city,
        "location_accuracy_meters": report.location_accuracy_meters,
        "address_verified": report.address_verified,
        
        # Metadata
        "keywords": report.keywords or [],
        "sentiment_score": report.sentiment_score,
        "is_duplicate": report.is_duplicate,
        
        # Timestamps
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "first_response_at": report.first_response_at,
        "resolved_at": report.resolved_at,
        
        # Reporter (limited info for privacy)
        "reporter_name": report.reporter.full_name if report.reporter else None,
        
        # Related data
        "files": files,
        "alerts": alerts,
        
        # Statistics
        "total_alerts": total_alerts,
        "successful_alerts": successful_alerts,
    }


# =============================================================================
# Report CRUD Endpoints
# =============================================================================

@router.post("/", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_report(
    request: ReportCreateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Create a new animal rescue report.
    
    This endpoint allows authenticated users to submit new reports about animals
    that need help. The report will be processed asynchronously and alerts will
    be sent to relevant organizations.
    """
    try:
        # Rate limiting
        await check_rate_limit(
            f"user:{current_user.id}",
            "create_report",
            limit=settings.MAX_REPORTS_PER_USER_PER_DAY,
            window=86400  # 24 hours
        )
        
        logger.info(
            "Creating new report",
            user_id=str(current_user.id),
            animal_type=request.animal_type.value,
            urgency=request.urgency_level.value
        )
        
        # Validate and enhance location
        location_data = request.location.dict()
        
        # Perform geocoding if only coordinates provided
        if not location_data.get("address") and location_data.get("latitude"):
            try:
                geocoded = await geocoding_service.reverse_geocode(
                    location_data["latitude"], location_data["longitude"]
                )
                if geocoded:
                    location_data.update(geocoded)
                    location_data["address_verified"] = True
            except Exception as e:
                logger.warning("Geocoding failed during report creation", error=str(e))
                location_data["address_verified"] = False
        
        # Perform NLP analysis
        nlp_results = {}
        try:
            nlp_results = await nlp_service.analyze_text(
                request.description, request.language
            )
        except Exception as e:
            logger.warning("NLP analysis failed", error=str(e))
        
        # Create report
        report = Report(
            reporter_id=current_user.id,
            title=request.title,
            description=request.description,
            animal_type=request.animal_type,
            urgency_level=request.urgency_level,
            status=ReportStatus.SUBMITTED,
            language=request.language,
            
            # Location data
            latitude=location_data["latitude"],
            longitude=location_data["longitude"],
            address=location_data.get("address"),
            city=location_data.get("city"),
            location_accuracy_meters=location_data.get("accuracy_meters"),
            address_verified=location_data.get("address_verified", False),
            
            # NLP results
            keywords=nlp_results.get("keywords", []),
            sentiment_score=nlp_results.get("sentiment"),
        )
        
        session.add(report)
        await session.commit()
        await session.refresh(report)
        
        # Queue background processing
        process_new_report.delay(str(report.id))
        
        # Update user statistics
        current_user.reports_count += 1
        await session.commit()
        
        logger.info(
            "Report created successfully",
            report_id=str(report.id),
            public_id=report.public_id,
            user_id=str(current_user.id)
        )
        
        # Return formatted response
        formatted_report = format_report_response(report)
        
        return {
            "success": True,
            "message": "Report created successfully",
            "report": formatted_report,
            "processing": {
                "status": "queued",
                "message": "Report is being processed and alerts will be sent to relevant organizations"
            }
        }
        
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {e.retry_after} seconds."
        )
        
    except Exception as e:
        logger.error("Failed to create report", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create report. Please try again."
        )


@router.get("/{report_id}", response_model=Dict[str, Any])
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get a specific report by ID or public ID.
    
    Public reports can be viewed by anyone, but private information
    is filtered based on user permissions.
    """
    try:
        report = await get_report_by_id_or_public_id(
            report_id, session, current_user
        )
        
        logger.info(
            "Report retrieved",
            report_id=str(report.id),
            public_id=report.public_id,
            user_id=str(current_user.id) if current_user else None
        )
        
        formatted_report = format_report_response(report)
        
        # Filter sensitive information for non-owners
        if (not current_user or 
            (current_user.id != report.reporter_id and 
             current_user.role not in [UserRole.SYSTEM_ADMIN])):
            
            # Remove sensitive fields
            formatted_report.pop("reporter_name", None)
            
            # Limit alert details
            for alert in formatted_report["alerts"]:
                alert.pop("external_id", None)
        
        return {
            "success": True,
            "report": formatted_report
        }
        
    except (NotFoundError, PermissionDeniedError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    
    except Exception as e:
        logger.error("Failed to get report", report_id=report_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve report"
        )


@router.put("/{report_id}", response_model=Dict[str, Any])
async def update_report(
    report_id: str,
    request: ReportUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Update an existing report.
    
    Only the report owner or authorized organization staff can update reports.
    Some fields may be restricted based on current status.
    """
    try:
        report = await get_report_by_id_or_public_id(
            report_id, session, current_user, require_owner=True
        )
        
        # Check if report can be updated
        if report.status in [ReportStatus.RESOLVED, ReportStatus.CLOSED]:
            raise ValidationError("Cannot update resolved or closed reports")
        
        # Update fields
        update_data = request.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            if hasattr(report, field):
                setattr(report, field, value)
        
        # Update timestamp
        report.updated_at = datetime.now(timezone.utc)
        
        # Re-run NLP analysis if description changed
        if "description" in update_data:
            try:
                nlp_results = await nlp_service.analyze_text(
                    report.description, report.language
                )
                if nlp_results.get("keywords"):
                    report.keywords = nlp_results["keywords"]
                if nlp_results.get("sentiment") is not None:
                    report.sentiment_score = nlp_results["sentiment"]
            except Exception as e:
                logger.warning("NLP re-analysis failed", error=str(e))
        
        await session.commit()
        await session.refresh(report)
        
        logger.info(
            "Report updated",
            report_id=str(report.id),
            updated_fields=list(update_data.keys()),
            user_id=str(current_user.id)
        )
        
        return {
            "success": True,
            "message": "Report updated successfully",
            "report": format_report_response(report)
        }
        
    except (NotFoundError, PermissionDeniedError, ValidationError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    except Exception as e:
        logger.error("Failed to update report", report_id=report_id, error=str(e))
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update report"
        )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles([UserRole.SYSTEM_ADMIN]))
):
    """
    Delete a report (admin only).
    
    This is a hard delete that removes the report and all associated data.
    Use with caution - prefer updating status to CLOSED instead.
    """
    try:
        report = await get_report_by_id_or_public_id(report_id, session)
        
        # Delete associated files from storage
        for file in report.files:
            try:
                await file_storage.delete_file(file.storage_path)
            except Exception as e:
                logger.warning("Failed to delete file from storage", file_id=str(file.id), error=str(e))
        
        # Delete from database (cascading will handle related records)
        await session.delete(report)
        await session.commit()
        
        logger.info(
            "Report deleted",
            report_id=str(report.id),
            public_id=report.public_id,
            admin_user_id=str(current_user.id)
        )
        
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    
    except Exception as e:
        logger.error("Failed to delete report", report_id=report_id, error=str(e))
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete report"
        )


# =============================================================================
# Report Search and Listing
# =============================================================================

@router.get("/", response_model=ReportListResponse)
async def list_reports(
    params: ReportSearchParams = Depends(),
    session: AsyncSession = Depends(get_db_session),
    current_user: Optional[User] = Depends(get_current_user)
) -> ReportListResponse:
    """
    List and search reports with filtering and pagination.
    
    Supports various search criteria including location, animal type,
    urgency level, and text search in titles and descriptions.
    """
    try:
        # Build base query
        query = select(Report).options(
            selectinload(Report.reporter),
            selectinload(Report.files),
            selectinload(Report.alerts).selectinload(Alert.organization)
        )
        
        # Apply access control
        conditions = []
        
        if current_user:
            if current_user.role == UserRole.REPORTER:
                # Users can only see their own reports
                conditions.append(Report.reporter_id == current_user.id)
            elif current_user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
                # Org staff can see reports assigned to their organization
                conditions.append(
                    or_(
                        Report.assigned_organization_id == current_user.organization_id,
                        Report.reporter_id == current_user.id  # Plus their own
                    )
                )
            # System admins can see all reports
        else:
            # Public access - only show non-sensitive completed reports
            conditions.append(
                and_(
                    Report.status.in_([ReportStatus.RESOLVED, ReportStatus.CLOSED]),
                    Report.is_duplicate == False
                )
            )
        
        # Apply search filters
        if params.query:
            search_term = f"%{params.query}%"
            conditions.append(
                or_(
                    Report.title.ilike(search_term),
                    Report.description.ilike(search_term),
                    Report.public_id.ilike(search_term)
                )
            )
        
        if params.animal_type:
            conditions.append(Report.animal_type == params.animal_type)
        
        if params.urgency_level:
            conditions.append(Report.urgency_level == params.urgency_level)
        
        if params.status:
            conditions.append(Report.status == params.status)
        
        if params.city:
            conditions.append(Report.city.ilike(f"%{params.city}%"))
        
        if params.language:
            conditions.append(Report.language == params.language)
        
        if params.date_from:
            conditions.append(Report.created_at >= params.date_from)
        
        if params.date_to:
            conditions.append(Report.created_at <= params.date_to)
        
        # Location-based search
        if params.latitude and params.longitude and params.radius_km:
            # Simple bounding box search (could be improved with PostGIS)
            lat_delta = params.radius_km / 111  # Rough conversion
            lon_delta = params.radius_km / (111 * 0.7)  # Rough longitude correction
            
            conditions.extend([
                Report.latitude.between(
                    params.latitude - lat_delta,
                    params.latitude + lat_delta
                ),
                Report.longitude.between(
                    params.longitude - lon_delta,
                    params.longitude + lon_delta
                )
            ])
        
        # Apply all conditions
        if conditions:
            query = query.where(and_(*conditions))
        
        # Sorting
        sort_column = getattr(Report, params.sort_by)
        if params.sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))
        
        # Count total results
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar()
        
        # Apply pagination
        offset = (params.page - 1) * params.page_size
        query = query.offset(offset).limit(params.page_size)
        
        # Execute query
        result = await session.execute(query)
        reports = result.scalars().all()
        
        # Format response
        formatted_reports = []
        for report in reports:
            formatted_report = format_report_response(report)
            
            # Filter sensitive data for public/limited access
            if (not current_user or 
                current_user.role == UserRole.REPORTER and 
                current_user.id != report.reporter_id):
                formatted_report.pop("reporter_name", None)
                # Limit alert details
                for alert in formatted_report["alerts"]:
                    alert.pop("external_id", None)
            
            formatted_reports.append(formatted_report)
        
        # Calculate pagination info
        total_pages = (total + params.page_size - 1) // params.page_size
        has_next = params.page < total_pages
        has_previous = params.page > 1
        
        logger.info(
            "Reports listed",
            total=total,
            page=params.page,
            page_size=params.page_size,
            user_id=str(current_user.id) if current_user else None
        )
        
        return ReportListResponse(
            reports=formatted_reports,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
            has_next=has_next,
            has_previous=has_previous
        )
        
    except Exception as e:
        logger.error("Failed to list reports", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reports"
        )


# =============================================================================
# File Upload Endpoints
# =============================================================================

@router.post("/{report_id}/files", response_model=Dict[str, Any])
async def upload_report_file(
    report_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Upload a file attachment to a report.
    
    Supports images, videos, and documents. Files are stored in cloud storage
    and metadata is saved to the database.
    """
    try:
        # Validate file
        if not file.filename:
            raise ValidationError("No file provided")
        
        if file.size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValidationError(f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
        
        # Check content type
        if file.content_type not in settings.ALLOWED_FILE_TYPES:
            raise ValidationError(f"File type {file.content_type} not allowed")
        
        # Get report and verify ownership
        report = await get_report_by_id_or_public_id(
            report_id, session, current_user, require_owner=True
        )
        
        # Check file limit per report
        if len(report.files) >= 5:  # Max 5 files per report
            raise ValidationError("Maximum number of files per report exceeded")
        
        # Read file data
        file_data = await file.read()
        
        # Upload to storage
        storage_result = await file_storage.upload_file(
            file_data=file_data,
            filename=file.filename,
            content_type=file.content_type,
            folder=f"reports/{report.id}"
        )
        
        # Determine file type
        file_type = "photo"
        if file.content_type.startswith("video/"):
            file_type = "video"
        elif file.content_type.startswith("audio/"):
            file_type = "audio"
        elif not file.content_type.startswith("image/"):
            file_type = "document"
        
        # Create file record
        report_file = ReportFile(
            report_id=report.id,
            filename=file.filename,
            file_type=file_type,
            mime_type=file.content_type,
            file_size_bytes=len(file_data),
            storage_backend=settings.STORAGE_BACKEND,
            storage_path=storage_result["path"],
            storage_url=storage_result.get("url"),
            file_hash=storage_result.get("hash"),
        )
        
        # For images, try to get dimensions
        if file_type == "photo":
            try:
                from PIL import Image
                import io
                
                image = Image.open(io.BytesIO(file_data))
                report_file.width = image.width
                report_file.height = image.height
            except Exception as e:
                logger.warning("Failed to get image dimensions", error=str(e))
        
        session.add(report_file)
        await session.commit()
        await session.refresh(report_file)
        
        logger.info(
            "File uploaded to report",
            report_id=str(report.id),
            file_id=str(report_file.id),
            filename=file.filename,
            file_size=len(file_data)
        )
        
        return {
            "success": True,
            "message": "File uploaded successfully",
            "file": {
                "id": str(report_file.id),
                "filename": report_file.filename,
                "file_type": report_file.file_type,
                "file_size_bytes": report_file.file_size_bytes,
                "storage_url": report_file.storage_url,
                "created_at": report_file.created_at,
            }
        }
        
    except (ValidationError, NotFoundError, PermissionDeniedError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    except Exception as e:
        logger.error("Failed to upload file", report_id=report_id, error=str(e))
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload file"
        )


# =============================================================================
# Status Updates and Organization Actions
# =============================================================================

@router.post("/{report_id}/status", response_model=Dict[str, Any])
async def update_report_status(
    report_id: str,
    status: ReportStatus,
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles([UserRole.ORG_STAFF, UserRole.ORG_ADMIN, UserRole.SYSTEM_ADMIN]))
) -> Dict[str, Any]:
    """
    Update report status (organization staff only).
    
    Allows organization staff to update the status of reports assigned
    to their organization and add notes about the progress.
    """
    try:
        report = await get_report_by_id_or_public_id(report_id, session)
        
        # Check permissions
        if (current_user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN] and
            current_user.organization_id != report.assigned_organization_id):
            raise PermissionDeniedError("You can only update reports assigned to your organization")
        
        old_status = report.status
        report.status = status
        
        # Update relevant timestamps
        if status == ReportStatus.ACKNOWLEDGED and not report.first_response_at:
            report.first_response_at = datetime.now(timezone.utc)
        elif status == ReportStatus.RESOLVED and not report.resolved_at:
            report.resolved_at = datetime.now(timezone.utc)
            # Update user success statistics
            result = await session.execute(
                select(User).where(User.id == report.reporter_id)
            )
            reporter = result.scalar_one_or_none()
            if reporter:
                reporter.successful_reports_count += 1
        
        # If assigning to organization
        if not report.assigned_organization_id and current_user.organization_id:
            report.assigned_organization_id = current_user.organization_id
        
        report.updated_at = datetime.now(timezone.utc)
        
        await session.commit()
        
        # Create audit event
        from app.models.database import Event, EventType
        event = Event(
            event_type=EventType.REPORT_STATUS_CHANGED,
            entity_type="report",
            entity_id=report.id,
            user_id=current_user.id,
            payload={
                "report_id": str(report.id),
                "old_status": old_status.value,
                "new_status": status.value,
                "notes": notes,
                "organization_id": str(current_user.organization_id) if current_user.organization_id else None,
            }
        )
        session.add(event)
        await session.commit()
        
        logger.info(
            "Report status updated",
            report_id=str(report.id),
            old_status=old_status.value,
            new_status=status.value,
            organization_id=str(current_user.organization_id) if current_user.organization_id else None
        )
        
        return {
            "success": True,
            "message": f"Report status updated to {status.value}",
            "report": format_report_response(report)
        }
        
    except (NotFoundError, PermissionDeniedError) as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    
    except Exception as e:
        logger.error("Failed to update report status", report_id=report_id, error=str(e))
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update report status"
        )


# =============================================================================
# Statistics and Analytics Endpoints
# =============================================================================

@router.get("/stats/summary", response_model=Dict[str, Any])
async def get_reports_summary(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_roles([UserRole.ORG_ADMIN, UserRole.SYSTEM_ADMIN]))
) -> Dict[str, Any]:
    """
    Get summary statistics for reports.
    
    Returns aggregated data about reports including counts by status,
    urgency level, animal type, and response times.
    """
    try:
        # Base conditions for user access
        conditions = []
        if current_user.role in [UserRole.ORG_STAFF, UserRole.ORG_ADMIN]:
            conditions.append(Report.assigned_organization_id == current_user.organization_id)
        
        base_query = select(Report)
        if conditions:
            base_query = base_query.where(and_(*conditions))
        
        # Total reports
        total_result = await session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total_reports = total_result.scalar()
        
        # Reports by status
        status_result = await session.execute(
            select(Report.status, func.count())
            .select_from(base_query.subquery())
            .group_by(Report.status)
        )
        reports_by_status = dict(status_result.all())
        
        # Reports by urgency
        urgency_result = await session.execute(
            select(Report.urgency_level, func.count())
            .select_from(base_query.subquery())
            .group_by(Report.urgency_level)
        )
        reports_by_urgency = dict(urgency_result.all())
        
        # Reports by animal type
        animal_result = await session.execute(
            select(Report.animal_type, func.count())
            .select_from(base_query.subquery())
            .group_by(Report.animal_type)
        )
        reports_by_animal = dict(animal_result.all())
        
        # Recent reports (last 7 days)
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_query = base_query.where(Report.created_at >= week_ago)
        
        recent_result = await session.execute(
            select(func.count()).select_from(recent_query.subquery())
        )
        recent_reports = recent_result.scalar()
        
        # Average response time
        response_time_result = await session.execute(
            select(func.avg(
                func.extract('epoch', Report.first_response_at - Report.created_at) / 60
            )).select_from(
                base_query.where(Report.first_response_at.isnot(None)).subquery()
            )
        )
        avg_response_time_minutes = response_time_result.scalar()
        
        return {
            "summary": {
                "total_reports": total_reports,
                "recent_reports": recent_reports,
                "avg_response_time_minutes": round(avg_response_time_minutes or 0, 2),
            },
            "breakdown": {
                "by_status": {status.value: count for status, count in reports_by_status.items()},
                "by_urgency": {urgency.value: count for urgency, count in reports_by_urgency.items()},
                "by_animal_type": {animal.value: count for animal, count in reports_by_animal.items()},
            },
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.error("Failed to get report statistics", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate statistics"
        )
