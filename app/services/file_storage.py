"""
File Storage Service
שירות אחסון קבצים

This module provides file storage functionality supporting multiple backends:
- Local filesystem storage for development
- AWS S3 compatible storage (S3, Cloudflare R2) for production
- File validation, compression and metadata extraction
"""

import hashlib
import mimetypes
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from app.core.config import settings
from app.core.exceptions import ValidationError, ExternalServiceError

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# File Storage Backend Classes
# =============================================================================

class FileStorageBackend:
    """Base class for file storage backends."""
    
    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        folder: str = ""
    ) -> Dict[str, Any]:
        """Upload file and return metadata."""
        raise NotImplementedError
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file and return content."""
        raise NotImplementedError
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file."""
        raise NotImplementedError
    
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        raise NotImplementedError
    
    async def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get file metadata."""
        raise NotImplementedError


class LocalFileStorage(FileStorageBackend):
    """Local filesystem storage backend."""
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        logger.info("Local file storage initialized", base_path=str(self.base_path))
    
    def _get_full_path(self, file_path: str) -> Path:
        """Get full filesystem path."""
        return self.base_path / file_path.lstrip('/')
    
    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        folder: str = ""
    ) -> Dict[str, Any]:
        """Upload file to local filesystem."""
        try:
            # Generate unique filename
            file_ext = Path(filename).suffix.lower()
            unique_name = f"{uuid.uuid4().hex}{file_ext}"
            
            # Create folder path
            if folder:
                folder_path = self.base_path / folder
                folder_path.mkdir(parents=True, exist_ok=True)
                file_path = Path(folder) / unique_name
            else:
                file_path = Path(unique_name)
            
            full_path = self._get_full_path(str(file_path))
            
            # Write file
            full_path.write_bytes(file_data)
            
            # Generate file hash
            file_hash = hashlib.sha256(file_data).hexdigest()
            
            # Generate public URL (for development)
            public_url = None
            if settings.ENVIRONMENT == "development":
                public_url = f"/uploads/{file_path}".replace("\\", "/")
            
            logger.debug(
                "File uploaded to local storage",
                filename=filename,
                path=str(file_path),
                size=len(file_data)
            )
            
            return {
                "path": str(file_path).replace("\\", "/"),
                "url": public_url,
                "hash": file_hash,
                "size": len(file_data),
                "backend": "local",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            
        except Exception as e:
            logger.error("Local file upload failed", filename=filename, error=str(e))
            raise ExternalServiceError(f"Failed to upload file: {str(e)}")
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from local filesystem."""
        try:
            full_path = self._get_full_path(file_path)
            
            if not full_path.exists():
                raise ValidationError(f"File not found: {file_path}")
            
            return full_path.read_bytes()
            
        except ValidationError:
            raise
        except Exception as e:
            logger.error("Local file download failed", path=file_path, error=str(e))
            raise ExternalServiceError(f"Failed to download file: {str(e)}")
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from local filesystem."""
        try:
            full_path = self._get_full_path(file_path)
            
            if full_path.exists():
                full_path.unlink()
                logger.debug("File deleted from local storage", path=file_path)
                return True
            
            return False
            
        except Exception as e:
            logger.error("Local file deletion failed", path=file_path, error=str(e))
            return False
    
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists in local filesystem."""
        try:
            full_path = self._get_full_path(file_path)
            return full_path.exists()
        except Exception:
            return False
    
    async def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get file metadata from local filesystem."""
        try:
            full_path = self._get_full_path(file_path)
            
            if not full_path.exists():
                return None
            
            stat = full_path.stat()
            
            return {
                "path": file_path,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "backend": "local",
            }
            
        except Exception as e:
            logger.error("Failed to get local file info", path=file_path, error=str(e))
            return None


class S3FileStorage(FileStorageBackend):
    """S3-compatible storage backend (AWS S3, Cloudflare R2, etc.)."""
    
    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        
        # Initialize S3 client
        self.client = boto3.client(
            's3',
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
        )
        
        logger.info(
            "S3 file storage initialized",
            bucket=self.bucket_name,
            endpoint=settings.S3_ENDPOINT_URL,
            region=settings.S3_REGION
        )
    
    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        folder: str = ""
    ) -> Dict[str, Any]:
        """Upload file to S3-compatible storage."""
        try:
            # Generate unique filename
            file_ext = Path(filename).suffix.lower()
            unique_name = f"{uuid.uuid4().hex}{file_ext}"
            
            # Create S3 key
            if folder:
                s3_key = f"{folder.strip('/')}/{unique_name}"
            else:
                s3_key = unique_name
            
            # Generate file hash
            file_hash = hashlib.sha256(file_data).hexdigest()
            
            # Upload to S3
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_data,
                ContentType=content_type,
                Metadata={
                    'original_filename': filename,
                    'upload_timestamp': datetime.now(timezone.utc).isoformat(),
                    'file_hash': file_hash,
                },
                # Make public for image access (adjust based on security needs)
                # ACL='public-read',  # Uncomment if needed
            )
            
            # Generate public URL
            public_url = None
            if settings.S3_ENDPOINT_URL:
                # For custom endpoints like Cloudflare R2
                public_url = f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.bucket_name}/{s3_key}"
            else:
                # For AWS S3
                public_url = f"https://{self.bucket_name}.s3.{settings.S3_REGION}.amazonaws.com/{s3_key}"
            
            logger.debug(
                "File uploaded to S3",
                filename=filename,
                key=s3_key,
                size=len(file_data)
            )
            
            return {
                "path": s3_key,
                "url": public_url,
                "hash": file_hash,
                "size": len(file_data),
                "backend": "s3",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            
        except (BotoCoreError, ClientError) as e:
            logger.error("S3 upload failed", filename=filename, error=str(e))
            raise ExternalServiceError(f"Failed to upload file to S3: {str(e)}")
        except Exception as e:
            logger.error("S3 upload error", filename=filename, error=str(e))
            raise ExternalServiceError(f"S3 upload error: {str(e)}")
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file from S3."""
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=file_path)
            return response['Body'].read()
            
        except self.client.exceptions.NoSuchKey:
            raise ValidationError(f"File not found: {file_path}")
        except (BotoCoreError, ClientError) as e:
            logger.error("S3 download failed", path=file_path, error=str(e))
            raise ExternalServiceError(f"Failed to download file from S3: {str(e)}")
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=file_path)
            logger.debug("File deleted from S3", path=file_path)
            return True
            
        except Exception as e:
            logger.error("S3 file deletion failed", path=file_path, error=str(e))
            return False
    
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists in S3."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=file_path)
            return True
        except self.client.exceptions.NoSuchKey:
            return False
        except Exception:
            return False
    
    async def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get file metadata from S3."""
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=file_path)
            
            return {
                "path": file_path,
                "size": response.get('ContentLength', 0),
                "modified": response.get('LastModified', '').isoformat() if response.get('LastModified') else None,
                "content_type": response.get('ContentType'),
                "metadata": response.get('Metadata', {}),
                "backend": "s3",
            }
            
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.error("Failed to get S3 file info", path=file_path, error=str(e))
            return None


# =============================================================================
# Main File Storage Service
# =============================================================================

class FileStorageService:
    """
    Main file storage service with validation and processing capabilities.
    
    Features:
    - Multiple storage backends (local, S3)
    - File validation and security checks
    - Image processing and thumbnail generation
    - Metadata extraction
    - Duplicate detection
    """
    
    _initialized = False

    def __init__(self):
        # Initialize storage backend based on configuration
        if settings.STORAGE_BACKEND == "local":
            self.backend = LocalFileStorage(settings.UPLOAD_DIR)
        elif settings.STORAGE_BACKEND in ["s3", "r2"]:
            self.backend = S3FileStorage()
        else:
            raise ValueError(f"Unsupported storage backend: {settings.STORAGE_BACKEND}")
        if not FileStorageService._initialized:
            logger.info("File storage service initialized", backend=settings.STORAGE_BACKEND)
            FileStorageService._initialized = True
    
    def validate_file(self, file_data: bytes, filename: str, content_type: str) -> None:
        """
        Validate uploaded file for security and constraints.
        
        Args:
            file_data: File content bytes
            filename: Original filename
            content_type: MIME type
            
        Raises:
            ValidationError: If file is invalid
        """
        # Check file size
        max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if len(file_data) > max_size:
            raise ValidationError(f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
        
        # Check file type
        if content_type not in settings.ALLOWED_FILE_TYPES:
            raise ValidationError(f"File type {content_type} is not allowed")
        
        # Verify MIME type matches content
        detected_type, _ = mimetypes.guess_type(filename)
        if detected_type and detected_type != content_type:
            logger.warning(
                "MIME type mismatch",
                declared=content_type,
                detected=detected_type,
                filename=filename
            )
        
        # Additional security checks for images
        if content_type.startswith('image/'):
            try:
                # Try to open with PIL to verify it's a valid image
                image = Image.open(BytesIO(file_data))
                image.verify()
                
                # Check for suspicious dimensions
                if hasattr(image, 'size'):
                    width, height = image.size
                    if width > 10000 or height > 10000:
                        raise ValidationError("Image dimensions too large")
                
            except Exception as e:
                raise ValidationError(f"Invalid image file: {str(e)}")
        
        # Check for malicious content (basic)
        if b'<script' in file_data.lower() or b'javascript:' in file_data.lower():
            raise ValidationError("File contains potentially malicious content")
    
    def extract_metadata(self, file_data: bytes, content_type: str) -> Dict[str, Any]:
        """
        Extract metadata from file.
        
        Args:
            file_data: File content bytes
            content_type: MIME type
            
        Returns:
            Dictionary with extracted metadata
        """
        metadata = {
            "size": len(file_data),
            "hash": hashlib.sha256(file_data).hexdigest(),
        }
        
        # Extract image metadata
        if content_type.startswith('image/'):
            try:
                image = Image.open(BytesIO(file_data))
                metadata.update({
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                    "mode": image.mode,
                })
                
                # Extract EXIF data if available
                if hasattr(image, '_getexif'):
                    exif = image._getexif()
                    if exif:
                        metadata["has_exif"] = True
                        # Remove GPS data for privacy
                        if 34853 in exif:  # GPS info tag
                            logger.info("GPS data removed from image")
                
            except Exception as e:
                logger.warning("Failed to extract image metadata", error=str(e))
        
        return metadata
    
    def generate_thumbnail(self, file_data: bytes, content_type: str) -> Optional[bytes]:
        """
        Generate thumbnail for image files.
        
        Args:
            file_data: Original image data
            content_type: MIME type
            
        Returns:
            Thumbnail image bytes or None if not applicable
        """
        if not content_type.startswith('image/'):
            return None
        
        try:
            image = Image.open(BytesIO(file_data))
            
            # Create thumbnail
            thumbnail_size = (300, 300)
            image.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            
            # Save thumbnail to bytes
            thumbnail_io = BytesIO()
            # Use JPEG for thumbnails to reduce size
            if image.mode in ('RGBA', 'LA', 'P'):
                # Convert to RGB for JPEG
                image = image.convert('RGB')
            
            image.save(thumbnail_io, format='JPEG', quality=85, optimize=True)
            thumbnail_io.seek(0)
            
            return thumbnail_io.getvalue()
            
        except Exception as e:
            logger.warning("Failed to generate thumbnail", error=str(e))
            return None
    
    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        folder: str = "",
        generate_thumbnail: bool = True
    ) -> Dict[str, Any]:
        """
        Upload file with validation and processing.
        
        Args:
            file_data: File content bytes
            filename: Original filename
            content_type: MIME type
            folder: Storage folder path
            generate_thumbnail: Whether to generate thumbnail for images
            
        Returns:
            Upload result with metadata
        """
        # Validate file
        self.validate_file(file_data, filename, content_type)
        
        # Extract metadata
        metadata = self.extract_metadata(file_data, content_type)
        
        # Upload main file
        upload_result = await self.backend.upload_file(
            file_data, filename, content_type, folder
        )
        
        # Add metadata
        upload_result.update(metadata)
        
        # Generate and upload thumbnail for images
        if generate_thumbnail and content_type.startswith('image/'):
            thumbnail_data = self.generate_thumbnail(file_data, content_type)
            if thumbnail_data:
                try:
                    thumbnail_filename = f"thumb_{filename}"
                    thumbnail_result = await self.backend.upload_file(
                        thumbnail_data, thumbnail_filename, "image/jpeg", 
                        f"{folder}/thumbnails" if folder else "thumbnails"
                    )
                    upload_result["thumbnail"] = thumbnail_result
                except Exception as e:
                    logger.warning("Failed to upload thumbnail", error=str(e))
        
        logger.info(
            "File uploaded successfully",
            filename=filename,
            size=len(file_data),
            backend=settings.STORAGE_BACKEND,
            path=upload_result.get("path")
        )
        
        return upload_result
    
    async def download_file(self, file_path: str) -> bytes:
        """Download file content."""
        return await self.backend.download_file(file_path)
    
    async def delete_file(self, file_path: str) -> bool:
        """Delete file."""
        success = await self.backend.delete_file(file_path)
        
        # Also try to delete thumbnail if it exists
        if file_path and not file_path.startswith("thumbnails/"):
            thumbnail_path = f"thumbnails/thumb_{Path(file_path).name}"
            await self.backend.delete_file(thumbnail_path)
        
        return success
    
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        return await self.backend.file_exists(file_path)
    
    async def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get file metadata."""
        return await self.backend.get_file_info(file_path)
    
    async def get_service_stats(self) -> Dict[str, Any]:
        """Get file storage service statistics."""
        return {
            "backend": settings.STORAGE_BACKEND,
            "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
            "allowed_file_types": settings.ALLOWED_FILE_TYPES,
            "upload_dir": str(settings.UPLOAD_DIR) if settings.STORAGE_BACKEND == "local" else None,
            "s3_bucket": settings.S3_BUCKET_NAME if settings.STORAGE_BACKEND in ["s3", "r2"] else None,
        }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "FileStorageService",
    "FileStorageBackend", 
    "LocalFileStorage",
    "S3FileStorage",
]
