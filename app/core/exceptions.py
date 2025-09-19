"""
Custom exception classes for the Animal Rescue Bot system.

This module defines all custom exceptions used throughout the application.
Each exception provides specific context for different error scenarios.
"""

from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class AnimalRescueException(Exception):
    """Base exception class for all Animal Rescue Bot exceptions."""
    
    def __init__(
        self,
        message: str = "An error occurred in Animal Rescue Bot",
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


# API/HTTP Exceptions
class APIException(AnimalRescueException, HTTPException):
    """Base HTTP exception for API errors."""
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        AnimalRescueException.__init__(self, message, error_code, details)
        HTTPException.__init__(self, status_code, message, headers)

# RateLimitExceededError
class RateLimitError(AnimalRescueException):
    """Base exception for rate limiting errors."""
    pass

class ValidationError(APIException):
    """Raised when data validation fails."""
    
    def __init__(
        self,
        message: str = "Validation failed",
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        if field and details is None:
            details = {"field": field}
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            details=details
        )


class NotFoundError(APIException):
    """Raised when a requested resource is not found."""
    
    def __init__(
        self,
        resource: str,
        identifier: Optional[str] = None,
        message: Optional[str] = None
    ):
        if message is None:
            message = f"{resource} not found"
            if identifier:
                message += f" (ID: {identifier})"
        
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="RESOURCE_NOT_FOUND",
            details={"resource": resource, "identifier": identifier}
        )


class PermissionDeniedError(APIException):
    """Raised when user lacks permission for an operation."""
    
    def __init__(
        self,
        message: str = "Permission denied",
        required_role: Optional[str] = None,
        resource: Optional[str] = None
    ):
        details = {}
        if required_role:
            details["required_role"] = required_role
        if resource:
            details["resource"] = resource
            
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="PERMISSION_DENIED",
            details=details
        )


class AuthenticationError(APIException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTHENTICATION_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"}
        )


class RateLimitExceededError(APIException):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None
    ):
        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)
            
        super().__init__(
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="RATE_LIMIT_EXCEEDED",
            headers=headers
        )


# Business Logic Exceptions
class ReportError(AnimalRescueException):
    """Base exception for report-related errors."""
    pass


class ReportNotFoundError(ReportError, NotFoundError):
    """Raised when a report is not found."""
    
    def __init__(self, report_id: str):
        super().__init__(
            resource="Report",
            identifier=report_id
        )


class ReportStatusError(ReportError):
    """Raised when report status transition is invalid."""
    
    def __init__(
        self,
        current_status: str,
        attempted_status: str,
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Cannot change report status from '{current_status}' to '{attempted_status}'"
        
        super().__init__(
            message=message,
            error_code="INVALID_STATUS_TRANSITION",
            details={
                "current_status": current_status,
                "attempted_status": attempted_status
            }
        )


class DuplicateReportError(ReportError):
    """Raised when a duplicate report is detected."""
    
    def __init__(
        self,
        similarity_score: float,
        existing_report_id: str,
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Possible duplicate report detected (similarity: {similarity_score:.2f})"
        
        super().__init__(
            message=message,
            error_code="DUPLICATE_REPORT",
            details={
                "similarity_score": similarity_score,
                "existing_report_id": existing_report_id
            }
        )


# External Service Exceptions
class ExternalServiceError(AnimalRescueException):
    """Base exception for external service errors."""
    
    def __init__(
        self,
        service_name: str,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"{service_name}: {message}",
            error_code="EXTERNAL_SERVICE_ERROR",
            details={
                "service": service_name,
                "status_code": status_code,
                "response_data": response_data
            }
        )
        self.service_name = service_name
        self.status_code = status_code


class GoogleAPIError(ExternalServiceError):
    """Raised when Google API calls fail."""
    
    def __init__(
        self,
        api_name: str,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            service_name=f"Google {api_name} API",
            message=message,
            status_code=status_code,
            response_data=response_data
        )


class TelegramAPIError(ExternalServiceError):
    """Raised when Telegram API calls fail."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None
    ):
        super().__init__(
            service_name="Telegram Bot API",
            message=message,
            status_code=status_code
        )
        if error_code:
            self.details["telegram_error_code"] = error_code


# Storage/File Exceptions
class StorageError(AnimalRescueException):
    """Base exception for file storage errors."""
    pass


class FileNotFoundError(StorageError):
    """Raised when a file is not found in storage."""
    
    def __init__(self, file_path: str, storage_backend: str = "unknown"):
        super().__init__(
            message=f"File not found: {file_path}",
            error_code="FILE_NOT_FOUND",
            details={
                "file_path": file_path,
                "storage_backend": storage_backend
            }
        )


class FileUploadError(StorageError):
    """Raised when file upload fails."""
    
    def __init__(
        self,
        message: str = "File upload failed",
        file_name: Optional[str] = None,
        file_size: Optional[int] = None
    ):
        details = {}
        if file_name:
            details["file_name"] = file_name
        if file_size:
            details["file_size"] = file_size
            
        super().__init__(
            message=message,
            error_code="FILE_UPLOAD_ERROR",
            details=details
        )


class FileSizeExceededError(FileUploadError):
    """Raised when uploaded file exceeds size limit."""
    
    def __init__(
        self,
        file_size: int,
        max_size: int,
        file_name: Optional[str] = None
    ):
        super().__init__(
            message=f"File size {file_size} bytes exceeds limit of {max_size} bytes",
            file_name=file_name,
            file_size=file_size
        )
        self.details.update({
            "max_size": max_size,
            "exceeded_by": file_size - max_size
        })


class UnsupportedFileTypeError(FileUploadError):
    """Raised when uploaded file type is not supported."""
    
    def __init__(
        self,
        file_type: str,
        supported_types: list[str],
        file_name: Optional[str] = None
    ):
        super().__init__(
            message=f"Unsupported file type: {file_type}. Supported types: {', '.join(supported_types)}",
            file_name=file_name
        )
        self.details.update({
            "file_type": file_type,
            "supported_types": supported_types
        })


# Database Exceptions
class DatabaseError(AnimalRescueException):
    """Base exception for database-related errors."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails."""
    
    def __init__(self, message: str = "Database connection failed"):
        super().__init__(
            message=message,
            error_code="DATABASE_CONNECTION_ERROR"
        )


# Worker/Queue Exceptions
class WorkerError(AnimalRescueException):
    """Base exception for background worker errors."""
    pass


class JobFailedError(WorkerError):
    """Raised when a background job fails."""
    
    def __init__(
        self,
        job_name: str,
        message: str,
        attempt: Optional[int] = None,
        max_attempts: Optional[int] = None
    ):
        details = {"job_name": job_name}
        if attempt is not None:
            details["attempt"] = attempt
        if max_attempts is not None:
            details["max_attempts"] = max_attempts
            
        super().__init__(
            message=f"Job '{job_name}' failed: {message}",
            error_code="JOB_FAILED",
            details=details
        )


class QueueError(WorkerError):
    """Raised when queue operations fail."""
    
    def __init__(self, queue_name: str, message: str):
        super().__init__(
            message=f"Queue '{queue_name}' error: {message}",
            error_code="QUEUE_ERROR",
            details={"queue_name": queue_name}
        )


# Configuration Exceptions
class ConfigurationError(AnimalRescueException):
    """Raised when configuration is invalid or missing."""
    
    def __init__(
        self,
        setting_name: str,
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Configuration error for setting: {setting_name}"
        
        super().__init__(
            message=message,
            error_code="CONFIGURATION_ERROR",
            details={"setting": setting_name}
        )


class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing."""
    
    def __init__(self, setting_name: str):
        super().__init__(
            setting_name=setting_name,
            message=f"Required configuration missing: {setting_name}"
        )
        self.error_code = "MISSING_CONFIGURATION"


# Cache/Redis Exceptions
class CacheError(AnimalRescueException):
    """Base exception for cache-related errors."""
    pass


class CacheConnectionError(CacheError):
    """Raised when cache connection fails."""
    
    def __init__(self, message: str = "Cache connection failed"):
        super().__init__(
            message=message,
            error_code="CACHE_CONNECTION_ERROR"
        )


class LockAcquisitionError(CacheError):
    """Raised when distributed lock cannot be acquired."""
    
    def __init__(
        self,
        lock_name: str,
        timeout: Optional[int] = None
    ):
        message = f"Could not acquire lock: {lock_name}"
        if timeout:
            message += f" (timeout: {timeout}s)"
        
        super().__init__(
            message=message,
            error_code="LOCK_ACQUISITION_FAILED",
            details={"lock_name": lock_name, "timeout": timeout}
        )


# NLP/AI Exceptions
class NLPError(AnimalRescueException):
    """Base exception for NLP processing errors."""
    pass


class TextAnalysisError(NLPError):
    """Raised when text analysis fails."""
    
    def __init__(
        self,
        text_snippet: str,
        analysis_type: str,
        message: Optional[str] = None
    ):
        if message is None:
            message = f"Text analysis failed for type: {analysis_type}"
        
        super().__init__(
            message=message,
            error_code="TEXT_ANALYSIS_ERROR",
            details={
                "analysis_type": analysis_type,
                "text_snippet": text_snippet[:100] + "..." if len(text_snippet) > 100 else text_snippet
            }
        )


class ModelLoadError(NLPError):
    """Raised when NLP model fails to load."""
    
    def __init__(self, model_name: str, message: Optional[str] = None):
        if message is None:
            message = f"Failed to load NLP model: {model_name}"
        
        super().__init__(
            message=message,
            error_code="MODEL_LOAD_ERROR",
            details={"model_name": model_name}
        )


# Utility functions for exception handling
def format_exception_for_logging(exc: Exception) -> Dict[str, Any]:
    """Format exception for structured logging."""
    data = {
        "exception_type": exc.__class__.__name__,
        "message": str(exc)
    }
    
    if isinstance(exc, AnimalRescueException):
        data["error_code"] = exc.error_code
        data["details"] = exc.details
    
    if isinstance(exc, APIException):
        data["status_code"] = exc.status_code
        if exc.headers:
            data["headers"] = exc.headers
    
    return data


def is_retryable_error(exc: Exception) -> bool:
    """Determine if an exception represents a retryable error."""
    # Network/connection errors are usually retryable
    if isinstance(exc, (DatabaseConnectionError, CacheConnectionError, ExternalServiceError)):
        return True
    
    # HTTP 5xx errors are typically retryable
    if isinstance(exc, APIException) and 500 <= exc.status_code < 600:
        return True
    
    # Rate limits are retryable after some time
    if isinstance(exc, RateLimitExceededError):
        return True
    
    # Specific external service errors that are temporary
    if isinstance(exc, ExternalServiceError):
        # Network timeouts, temporary unavailability etc.
        if exc.status_code in [408, 429, 502, 503, 504]:
            return True
    
    return False
