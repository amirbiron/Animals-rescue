"""
Admin interface routes for the Animal Rescue Bot system.

Provides comprehensive admin panel for system management including:
- User and organization management
- Report monitoring and statistics
- System health and worker monitoring
- Configuration management
- Alert management
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

import structlog
from app.core.config import settings
from app.core.security import (
    require_admin,
    require_roles,
    get_current_user
)
from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError
)
from app.models.database import (
    get_db_session,
    User, Organization, Report, Alert, Event,
    UserRole, ReportStatus, UrgencyLevel, AlertStatus
)
from app.services.email import email_service
from app.services.telegram_alerts import telegram_alerts
from app.services.google import GoogleService
from app.services.nlp import NLPService  
from app.workers.manager import worker_manager
from app.workers.jobs import (
    send_test_alert,
    generate_daily_statistics,
    cleanup_old_data,
    retry_failed_alerts
)
from app.core.cache import redis_client
from app.core.i18n import get_supported_languages

logger = structlog.get_logger(__name__)

# Create admin router
admin_router = APIRouter(prefix="/admin", tags=["admin"])


# Pydantic models for admin API
class AdminStats(BaseModel):
    """Admin dashboard statistics."""
    users_total: int
    users_active_24h: int
    organizations_total: int
    reports_total: int
    reports_today: int
    reports_pending: int
    reports_critical: int
    alerts_sent_today: int
    alerts_failed_today: int
    system_uptime_hours: float
    workers_active: int
    queues_total_jobs: int


class SystemHealth(BaseModel):
    """System health status."""
    status: str  # healthy, warning, critical
    database: Dict[str, Any]
    redis: Dict[str, Any]
    workers: Dict[str, Any]
    external_services: Dict[str, Any]
    memory_usage: Dict[str, Any]
    disk_usage: Dict[str, Any]


class UserManagement(BaseModel):
    """User management data."""
    id: str
    username: Optional[str]
    email: Optional[str]
    role: UserRole
    telegram_user_id: Optional[int]
    trust_score: float
    is_active: bool
    reports_count: int
    last_active: Optional[datetime]
    organization_name: Optional[str]


class OrganizationManagement(BaseModel):
    """Organization management data."""
    id: str
    name: str
    organization_type: str
    location: Optional[Dict[str, float]]  # lat, lng
    service_radius_km: Optional[float]
    staff_count: int
    reports_assigned: int
    alerts_sent_24h: int
    response_time_avg: Optional[float]
    is_active: bool


class ReportManagement(BaseModel):
    """Report management data."""
    id: str
    public_id: str
    title: Optional[str]
    status: ReportStatus
    urgency_level: UrgencyLevel
    animal_type: Optional[str]
    reporter_name: Optional[str]
    assigned_org: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    location_address: Optional[str]
    alerts_sent: int


class BulkActionRequest(BaseModel):
    """Request for bulk actions."""
    action: str  # activate, deactivate, delete, assign, etc.
    ids: List[str]
    parameters: Optional[Dict[str, Any]] = None


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""
    key: str
    value: Any
    category: str  # system, features, limits, etc.


# Dashboard and overview
@admin_router.get("/", response_class=HTMLResponse)
async def admin_dashboard(current_user: User = Depends(require_admin)):
    """Render admin dashboard HTML."""
    # This would typically render an HTML template
    # For now, return a simple dashboard page
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Animal Rescue Bot - Admin Panel</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
            .card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; }
            .card h3 { margin-top: 0; color: #333; }
            .stat { font-size: 24px; font-weight: bold; color: #007bff; }
            .btn { padding: 8px 16px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }
        </style>
    </head>
    <body>
        <h1>🐕 Animal Rescue Bot - Admin Panel</h1>
        
        <div class="dashboard">
            <div class="card">
                <h3>📊 Quick Stats</h3>
                <p>Total Reports: <span class="stat" id="reports-total">Loading...</span></p>
                <p>Pending Reports: <span class="stat" id="reports-pending">Loading...</span></p>
                <p>Active Users: <span class="stat" id="users-active">Loading...</span></p>
            </div>
            
            <div class="card">
                <h3>⚙️ System Health</h3>
                <p>Status: <span class="stat" id="system-status">Loading...</span></p>
                <p>Workers: <span class="stat" id="workers-count">Loading...</span></p>
                <p>Uptime: <span class="stat" id="system-uptime">Loading...</span></p>
            </div>
            
            <div class="card">
                <h3>🚀 Quick Actions</h3>
                <a href="/admin/reports" class="btn">Manage Reports</a><br><br>
                <a href="/admin/users" class="btn">Manage Users</a><br><br>
                <a href="/admin/organizations" class="btn">Organizations</a><br><br>
                <a href="/admin/system" class="btn">System Settings</a>
            </div>
        </div>
        
        <script>
            // Load dashboard stats
            fetch('/admin/stats')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('reports-total').textContent = data.reports_total;
                    document.getElementById('reports-pending').textContent = data.reports_pending;
                    document.getElementById('users-active').textContent = data.users_active_24h;
                });
            
            fetch('/admin/health')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('system-status').textContent = data.status;
                    document.getElementById('workers-count').textContent = data.workers.active_count || 0;
                    document.getElementById('system-uptime').textContent = 
                        Math.round(data.system_uptime_hours || 0) + 'h';
                });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@admin_router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """Get comprehensive admin statistics."""
    try:
        # Basic counts
        users_total = await db.scalar(select(func.count(User.id)))
        orgs_total = await db.scalar(select(func.count(Organization.id)))
        reports_total = await db.scalar(select(func.count(Report.id)))
        
        # Time-based queries
        today = datetime.utcnow().date()
        yesterday = datetime.utcnow() - timedelta(days=1)
        
        reports_today = await db.scalar(
            select(func.count(Report.id)).where(
                func.date(Report.created_at) == today
            )
        )
        
        users_active_24h = await db.scalar(
            select(func.count(User.id)).where(
                User.last_login > yesterday
            )
        ) or 0
        
        reports_pending = await db.scalar(
            select(func.count(Report.id)).where(
                Report.status.in_(['submitted', 'pending', 'acknowledged'])
            )
        )
        
        reports_critical = await db.scalar(
            select(func.count(Report.id)).where(
                and_(
                    Report.urgency_level == UrgencyLevel.CRITICAL,
                    Report.status != ReportStatus.RESOLVED
                )
            )
        )
        
        alerts_sent_today = await db.scalar(
            select(func.count(Alert.id)).where(
                and_(
                    func.date(Alert.created_at) == today,
                    Alert.status == AlertStatus.SENT
                )
            )
        ) or 0
        
        alerts_failed_today = await db.scalar(
            select(func.count(Alert.id)).where(
                and_(
                    func.date(Alert.created_at) == today,
                    Alert.status == AlertStatus.FAILED
                )
            )
        ) or 0
        
        # System stats
        worker_status = await worker_manager.get_status()
        workers_active = len([
            w for w in worker_status.get('workers', {}).values() 
            if w.get('is_alive', False)
        ])
        
        queues_total_jobs = sum(
            q.get('pending', 0) for q in worker_status.get('queues', {}).values()
            if isinstance(q, dict)
        )
        
        system_uptime_hours = worker_status.get('uptime_seconds', 0) / 3600
        
        return AdminStats(
            users_total=users_total or 0,
            users_active_24h=users_active_24h,
            organizations_total=orgs_total or 0,
            reports_total=reports_total or 0,
            reports_today=reports_today or 0,
            reports_pending=reports_pending or 0,
            reports_critical=reports_critical or 0,
            alerts_sent_today=alerts_sent_today,
            alerts_failed_today=alerts_failed_today,
            system_uptime_hours=system_uptime_hours,
            workers_active=workers_active,
            queues_total_jobs=queues_total_jobs
        )
        
    except Exception as e:
        logger.error("Error getting admin stats", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get statistics")


@admin_router.get("/health", response_model=SystemHealth)
async def get_system_health(current_user: User = Depends(require_admin)):
    """Get comprehensive system health status."""
    health_status = "healthy"
    issues = []
    
    try:
        # Database health
        db_health = {"status": "healthy", "latency_ms": 0}
        try:
            start_time = datetime.utcnow()
            async with get_db_session() as session:
                await session.execute(select(1))
            db_health["latency_ms"] = (datetime.utcnow() - start_time).total_seconds() * 1000
        except Exception as e:
            db_health = {"status": "error", "error": str(e)}
            health_status = "critical"
            issues.append("Database connection failed")
        
        # Redis health
        redis_health = {"status": "healthy", "latency_ms": 0}
        try:
            start_time = datetime.utcnow()
            await redis_client.ping()
            redis_health["latency_ms"] = (datetime.utcnow() - start_time).total_seconds() * 1000
        except Exception as e:
            redis_health = {"status": "error", "error": str(e)}
            health_status = "critical" if health_status != "critical" else health_status
            issues.append("Redis connection failed")
        
        # Workers health
        worker_status = await worker_manager.get_status()
        workers_health = {
            "status": "healthy" if worker_status["manager_status"] == "running" else "error",
            "active_workers": len([
                w for w in worker_status.get('workers', {}).values() 
                if w.get('is_alive', False)
            ]),
            "total_workers": len(worker_status.get('workers', {})),
            "queues": worker_status.get('queues', {})
        }
        
        if workers_health["active_workers"] == 0:
            health_status = "critical"
            issues.append("No active workers")
        elif workers_health["active_workers"] < workers_health["total_workers"]:
            if health_status == "healthy":
                health_status = "warning"
            issues.append("Some workers are down")
        
        # External services health
        external_services = {}
        
        # Email service
        try:
            email_status = await email_service.test_email_connection()
            external_services["email"] = email_status
            if email_status["status"] != "healthy":
                if health_status == "healthy":
                    health_status = "warning"
                issues.append("Email service issues")
        except Exception as e:
            external_services["email"] = {"status": "error", "error": str(e)}
        
        # Telegram service
        try:
            telegram_info = await telegram_alerts.get_bot_info()
            external_services["telegram"] = {
                "status": "healthy" if "error" not in telegram_info else "error",
                **telegram_info
            }
        except Exception as e:
            external_services["telegram"] = {"status": "error", "error": str(e)}
        
        # System resources
        import psutil
        memory_usage = {
            "total_mb": psutil.virtual_memory().total / 1024 / 1024,
            "used_mb": psutil.virtual_memory().used / 1024 / 1024,
            "percent": psutil.virtual_memory().percent
        }
        
        disk_usage = {
            "total_gb": psutil.disk_usage('/').total / 1024 / 1024 / 1024,
            "used_gb": psutil.disk_usage('/').used / 1024 / 1024 / 1024,
            "percent": psutil.disk_usage('/').used / psutil.disk_usage('/').total * 100
        }
        
        # Check resource thresholds
        if memory_usage["percent"] > 90:
            health_status = "critical"
            issues.append("High memory usage")
        elif memory_usage["percent"] > 80:
            if health_status == "healthy":
                health_status = "warning"
            issues.append("Memory usage above 80%")
        
        if disk_usage["percent"] > 95:
            health_status = "critical"
            issues.append("Disk space critical")
        elif disk_usage["percent"] > 85:
            if health_status == "healthy":
                health_status = "warning"
            issues.append("Disk space running low")
        
        return SystemHealth(
            status=health_status,
            database=db_health,
            redis=redis_health,
            workers=workers_health,
            external_services=external_services,
            memory_usage=memory_usage,
            disk_usage=disk_usage
        )
        
    except Exception as e:
        logger.error("Error getting system health", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get system health")


# User Management
@admin_router.get("/users", response_model=List[UserManagement])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    role: Optional[UserRole] = Query(None),
    active_only: bool = Query(False),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """List users with filtering and pagination."""
    
    query = select(User).options(selectinload(User.organization))
    
    # Apply filters
    conditions = []
    if role:
        conditions.append(User.role == role)
    if active_only:
        conditions.append(User.is_active == True)
    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                User.username.ilike(search_term),
                User.email.ilike(search_term),
                User.telegram_user_id == search if search.isdigit() else False
            )
        )
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.offset(skip).limit(limit).order_by(desc(User.created_at))
    
    users = (await db.execute(query)).scalars().all()
    
    result = []
    for user in users:
        # Get user report count
        reports_count = await db.scalar(
            select(func.count(Report.id)).where(Report.reporter_id == user.id)
        ) or 0
        
        result.append(UserManagement(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
            telegram_user_id=user.telegram_user_id,
            trust_score=user.trust_score,
            is_active=user.is_active,
            reports_count=reports_count,
            last_active=user.last_login,
            organization_name=user.organization.name if user.organization else None
        ))
    
    return result


@admin_router.post("/users/{user_id}/role")
async def update_user_role(
    user_id: str = Path(...),
    new_role: UserRole = Body(..., embed=True),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """Update user role."""
    
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError("User", user_id)
    
    old_role = user.role
    user.role = new_role
    user.updated_at = datetime.utcnow()
    
    await db.commit()
    
    # Log the change
    logger.info(
        "User role updated",
        user_id=user_id,
        old_role=old_role.value,
        new_role=new_role.value,
        admin_user_id=str(current_user.id)
    )
    
    return {"message": "User role updated successfully"}


@admin_router.post("/users/bulk-action")
async def bulk_user_action(
    request: BulkActionRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """Perform bulk actions on users."""
    
    if not request.ids:
        raise ValidationError("No user IDs provided")
    
    users = await db.execute(
        select(User).where(User.id.in_(request.ids))
    )
    users = users.scalars().all()
    
    if len(users) != len(request.ids):
        raise ValidationError("Some user IDs not found")
    
    updated_count = 0
    
    if request.action == "activate":
        for user in users:
            user.is_active = True
            updated_count += 1
    elif request.action == "deactivate":
        for user in users:
            user.is_active = False
            updated_count += 1
    elif request.action == "set_role":
        if not request.parameters or "role" not in request.parameters:
            raise ValidationError("Role parameter required")
        new_role = UserRole(request.parameters["role"])
        for user in users:
            user.role = new_role
            updated_count += 1
    else:
        raise ValidationError(f"Unknown action: {request.action}")
    
    await db.commit()
    
    logger.info(
        "Bulk user action performed",
        action=request.action,
        user_count=updated_count,
        admin_user_id=str(current_user.id)
    )
    
    return {"message": f"Updated {updated_count} users"}


# Organization Management
@admin_router.get("/organizations", response_model=List[OrganizationManagement])
async def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    org_type: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """List organizations with statistics."""
    
    query = select(Organization)
    
    if org_type:
        query = query.where(Organization.organization_type == org_type)
    
    query = query.offset(skip).limit(limit).order_by(Organization.name)
    
    organizations = (await db.execute(query)).scalars().all()
    
    result = []
    for org in organizations:
        # Get staff count
        staff_count = await db.scalar(
            select(func.count(User.id)).where(User.organization_id == org.id)
        ) or 0
        
        # Get assigned reports count
        reports_assigned = await db.scalar(
            select(func.count(Report.id)).where(Report.assigned_organization_id == org.id)
        ) or 0
        
        # Get alerts sent in last 24h
        yesterday = datetime.utcnow() - timedelta(days=1)
        alerts_sent_24h = await db.scalar(
            select(func.count(Alert.id)).where(
                and_(
                    Alert.organization_id == org.id,
                    Alert.created_at > yesterday,
                    Alert.status == AlertStatus.SENT
                )
            )
        ) or 0
        
        result.append(OrganizationManagement(
            id=str(org.id),
            name=org.name,
            organization_type=org.organization_type.value,
            location={"lat": org.latitude, "lng": org.longitude} if org.latitude and org.longitude else None,
            service_radius_km=org.service_radius_km,
            staff_count=staff_count,
            reports_assigned=reports_assigned,
            alerts_sent_24h=alerts_sent_24h,
            response_time_avg=None,  # TODO: Calculate from events
            is_active=org.is_active
        ))
    
    return result


# Report Management  
@admin_router.get("/reports", response_model=List[ReportManagement])
async def list_reports(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[ReportStatus] = Query(None),
    urgency: Optional[UrgencyLevel] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session)
):
    """List reports with filtering."""
    
    query = select(Report).options(
        selectinload(Report.reporter),
        selectinload(Report.assigned_organization)
    )
    
    conditions = []
    if status:
        conditions.append(Report.status == status)
    if urgency:
        conditions.append(Report.urgency_level == urgency)
    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                Report.title.ilike(search_term),
                Report.description.ilike(search_term),
                Report.public_id.ilike(search_term)
            )
        )
    
    if conditions:
        query = query.where(and_(*conditions))
    
    query = query.offset(skip).limit(limit).order_by(desc(Report.created_at))
    
    reports = (await db.execute(query)).scalars().all()
    
    result = []
    for report in reports:
        # Get alerts count
        alerts_sent = await db.scalar(
            select(func.count(Alert.id)).where(Alert.report_id == report.id)
        ) or 0
        
        result.append(ReportManagement(
            id=str(report.id),
            public_id=report.public_id,
            title=report.title,
            status=report.status,
            urgency_level=report.urgency_level,
            animal_type=report.animal_type.value if report.animal_type else None,
            reporter_name=report.reporter.username if report.reporter else None,
            assigned_org=report.assigned_organization.name if report.assigned_organization else None,
            created_at=report.created_at,
            updated_at=report.updated_at,
            location_address=report.address,
            alerts_sent=alerts_sent
        ))
    
    return result


# System Management
@admin_router.post("/system/test-alerts")
async def test_system_alerts(
    current_user: User = Depends(require_admin)
):
    """Send test alerts to verify system functionality."""
    
    results = {}
    
    # Test email
    try:
        email_result = await email_service.test_email_connection()
        results["email"] = email_result
    except Exception as e:
        results["email"] = {"status": "error", "error": str(e)}
    
    # Test Telegram
    try:
        # Use admin's telegram_user_id if available
        if current_user.telegram_user_id:
            telegram_result = await telegram_alerts.send_test_message(current_user.telegram_user_id)
            results["telegram"] = telegram_result
        else:
            results["telegram"] = {"status": "skipped", "reason": "No telegram_user_id for admin"}
    except Exception as e:
        results["telegram"] = {"status": "error", "error": str(e)}
    
    # Test worker queue
    try:
        job = send_test_alert.delay("Admin panel test message")
        results["workers"] = {"status": "queued", "job_id": job.id}
    except Exception as e:
        results["workers"] = {"status": "error", "error": str(e)}
    
    return {"test_results": results}


@admin_router.post("/system/maintenance/{action}")
async def run_maintenance_action(
    action: str = Path(...),
    current_user: User = Depends(require_admin)
):
    """Run system maintenance actions."""
    
    if action == "cleanup_old_data":
        job = cleanup_old_data.delay()
        return {"message": "Data cleanup job started", "job_id": job.id}
    
    elif action == "retry_failed_alerts":
        job = retry_failed_alerts.delay()
        return {"message": "Alert retry job started", "job_id": job.id}
    
    elif action == "generate_statistics":
        job = generate_daily_statistics.delay()
        return {"message": "Statistics generation started", "job_id": job.id}
    
    elif action == "restart_workers":
        try:
            await worker_manager.stop()
            await asyncio.sleep(2)
            await worker_manager.start()
            return {"message": "Workers restarted successfully"}
        except Exception as e:
            logger.error("Failed to restart workers", error=str(e))
            raise HTTPException(status_code=500, detail=f"Failed to restart workers: {str(e)}")
    
    else:
        raise ValidationError(f"Unknown maintenance action: {action}")


@admin_router.get("/system/config")
async def get_system_config(current_user: User = Depends(require_admin)):
    """Get system configuration (non-sensitive values only)."""
    
    config = {
        "app": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG
        },
        "features": {
            "supported_languages": get_supported_languages(),
            "max_file_size_mb": getattr(settings, 'MAX_FILE_SIZE_MB', 10),
            "rate_limiting_enabled": True,
            "trust_system_enabled": getattr(settings, 'ENABLE_TRUST_SYSTEM', False)
        },
        "limits": {
            "max_reports_per_user_per_day": getattr(settings, 'MAX_REPORTS_PER_USER_PER_DAY', 5),
            "search_radius_km": getattr(settings, 'SEARCH_RADIUS_KM', 10),
            "alert_timeout_minutes": getattr(settings, 'ALERT_TIMEOUT_MINUTES', 30)
        },
        "workers": {
            "worker_processes": getattr(settings, 'WORKER_PROCESSES', 2),
            "worker_timeout": getattr(settings, 'WORKER_TIMEOUT', 300),
            "job_max_retries": getattr(settings, 'JOB_MAX_RETRIES', 3)
        }
    }
    
    return config


@admin_router.get("/logs")
async def get_recent_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None),
    current_user: User = Depends(require_admin)
):
    """Get recent application logs."""
    
    # This would typically read from log files or logging service
    # For now, return recent events from database
    
    try:
        query = select(Event).order_by(desc(Event.created_at)).limit(limit)
        
        if level:
            # Filter by event type as proxy for log level
            if level.upper() == "ERROR":
                query = query.where(Event.event_type.in_(['error', 'alert_failed', 'job_failed']))
        
        async with get_db_session() as db:
            events = (await db.execute(query)).scalars().all()
        
        logs = []
        for event in events:
            logs.append({
                "timestamp": event.created_at.isoformat(),
                "level": "ERROR" if event.event_type in ['error', 'alert_failed', 'job_failed'] else "INFO",
                "event_type": event.event_type.value,
                "message": event.payload.get('message', 'No message') if event.payload else 'No payload',
                "details": event.payload
            })
        
        return {"logs": logs}
        
    except Exception as e:
        logger.error("Error retrieving logs", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")


# Export admin router
__all__ = ["admin_router"]
