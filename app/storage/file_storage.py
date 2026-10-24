import os
import uuid
import io
import shutil
import tempfile
from typing import Optional, Iterator, Tuple
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class LocalFileStorage:
    """Local filesystem storage adapter for development and testing."""

    def __init__(self, upload_dir: Optional[str] = None):
        self.upload_dir = upload_dir or settings.UPLOAD_DIR
        os.makedirs(self.upload_dir, exist_ok=True)

    def validate_file(self, file: UploadFile) -> str:
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type '{file.content_type}'. Allowed types: {list(ALLOWED_MIME_TYPES.keys())}"
            )
        return ALLOWED_MIME_TYPES[file.content_type]

    def save_upload_sync(self, file: UploadFile) -> Tuple[str, int]:
        ext = self.validate_file(file)
        unique_name = f"{uuid.uuid4()}{ext}"
        target_path = os.path.join(self.upload_dir, unique_name)

        size = 0
        with open(target_path, "wb") as out_file:
            while chunk := file.file.read(1024 * 64):
                size += len(chunk)
                if size > settings.MAX_UPLOAD_SIZE_BYTES:
                    out_file.close()
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_BYTES / (1024*1024):.1f}MB"
                    )
                out_file.write(chunk)

        return target_path, size

    def resolve_path(self, file_path: str) -> Optional[str]:
        """Resolves file path whether stored as absolute, relative, or raw filename."""
        if not file_path:
            return None
        if os.path.exists(file_path):
            return file_path
        fallback = os.path.join(self.upload_dir, os.path.basename(file_path))
        if os.path.exists(fallback):
            return fallback
        return None

    def object_exists(self, file_path: str) -> bool:
        return self.resolve_path(file_path) is not None

    def read_bytes(self, file_path: str) -> Optional[bytes]:
        resolved = self.resolve_path(file_path)
        if resolved and os.path.exists(resolved):
            with open(resolved, "rb") as f:
                return f.read()
        return None

    def get_stream(self, file_path: str) -> Optional[Iterator[bytes]]:
        resolved = self.resolve_path(file_path)
        if not resolved or not os.path.exists(resolved):
            return None

        def _iter_file():
            with open(resolved, "rb") as f:
                while chunk := f.read(1024 * 64):
                    yield chunk

        return _iter_file()


class S3CompatibleStorage:
    """
    S3-compatible persistent object-storage adapter supporting Cloudflare R2 and AWS S3.
    Stores clean object keys ('evidence/<uuid>.<ext>') and enforces private object visibility by default.
    Transparently handles legacy SQLite local filesystem paths via disk fallback.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        bucket_name: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: Optional[str] = None,
        upload_dir: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or settings.STORAGE_ENDPOINT
        self.bucket_name = bucket_name or settings.STORAGE_BUCKET
        self.access_key = access_key or settings.STORAGE_ACCESS_KEY
        self.secret_key = secret_key or settings.STORAGE_SECRET_KEY
        self.region = region or settings.STORAGE_REGION or "auto"
        self.upload_dir = upload_dir or settings.UPLOAD_DIR
        self.cache_dir = os.path.join(self.upload_dir, ".cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.client import Config
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 storage backend requested but 'boto3' is not installed."
            )

        kwargs = {
            "service_name": "s3",
            "region_name": self.region,
            "config": Config(signature_version="s3v4"),
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key

        self._client = boto3.client(**kwargs)
        return self._client

    def validate_file(self, file: UploadFile) -> str:
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type '{file.content_type}'. Allowed types: {list(ALLOWED_MIME_TYPES.keys())}"
            )
        return ALLOWED_MIME_TYPES[file.content_type]

    def save_upload_sync(self, file: UploadFile) -> Tuple[str, int]:
        ext = self.validate_file(file)
        unique_key = f"evidence/{uuid.uuid4()}{ext}"

        # Read in chunks and enforce size limits before sending to cloud storage
        buffer = bytearray()
        size = 0
        while chunk := file.file.read(1024 * 64):
            size += len(chunk)
            if size > settings.MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_BYTES / (1024*1024):.1f}MB"
                )
            buffer.extend(chunk)

        if not self.bucket_name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cloud storage error: STORAGE_BUCKET is not configured."
            )

        try:
            client = self._get_client()
            # Object is private by default; no public ACL is set
            client.put_object(
                Bucket=self.bucket_name,
                Key=unique_key,
                Body=bytes(buffer),
                ContentType=file.content_type or "image/jpeg",
                Metadata={
                    "original_filename": file.filename or "attachment.jpg"
                }
            )
        except HTTPException:
            raise
        except Exception as exc:
            # Mask credentials/raw connection details in exception message
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store evidence object safely in cloud storage."
            )

        return unique_key, size

    def resolve_path(self, file_path_or_key: str) -> Optional[str]:
        """
        Resolves path for local or remote object:
        1. Checks local filesystem first (seamlessly handles legacy SQLite evidence paths).
        2. If remote S3 key, checks S3 and caches locally so Pillow/CLIP can inspect it.
        """
        if not file_path_or_key:
            return None

        # 1. Local disk check (legacy SQLite absolute or relative paths)
        if os.path.exists(file_path_or_key):
            return file_path_or_key
        fallback_local = os.path.join(self.upload_dir, os.path.basename(file_path_or_key))
        if os.path.exists(fallback_local):
            return fallback_local

        # 2. Remote S3 object check and local caching
        clean_key = file_path_or_key.replace("\\", "/").lstrip("/")
        cache_path = os.path.join(self.cache_dir, os.path.basename(clean_key))
        if os.path.exists(cache_path):
            return cache_path

        if not self.bucket_name:
            return None

        try:
            client = self._get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=clean_key)
            with open(cache_path, "wb") as f:
                for chunk in response["Body"].iter_chunks(1024 * 64):
                    f.write(chunk)
            return cache_path
        except Exception:
            return None

    def object_exists(self, file_path_or_key: str) -> bool:
        if not file_path_or_key:
            return False
        if os.path.exists(file_path_or_key):
            return True
        fallback_local = os.path.join(self.upload_dir, os.path.basename(file_path_or_key))
        if os.path.exists(fallback_local):
            return True

        if not self.bucket_name:
            return False

        clean_key = file_path_or_key.replace("\\", "/").lstrip("/")
        try:
            client = self._get_client()
            client.head_object(Bucket=self.bucket_name, Key=clean_key)
            return True
        except Exception:
            return False

    def read_bytes(self, file_path_or_key: str) -> Optional[bytes]:
        resolved = self.resolve_path(file_path_or_key)
        if resolved and os.path.exists(resolved):
            with open(resolved, "rb") as f:
                return f.read()

        if not self.bucket_name:
            return None

        clean_key = file_path_or_key.replace("\\", "/").lstrip("/")
        try:
            client = self._get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=clean_key)
            return response["Body"].read()
        except Exception:
            return None

    def get_stream(self, file_path_or_key: str) -> Optional[Iterator[bytes]]:
        # If available locally, stream from disk
        if file_path_or_key and os.path.exists(file_path_or_key):
            def _iter_local():
                with open(file_path_or_key, "rb") as f:
                    while chunk := f.read(1024 * 64):
                        yield chunk
            return _iter_local()

        if not self.bucket_name:
            return None

        clean_key = file_path_or_key.replace("\\", "/").lstrip("/")
        try:
            client = self._get_client()
            response = client.get_object(Bucket=self.bucket_name, Key=clean_key)

            def _iter_s3():
                for chunk in response["Body"].iter_chunks(1024 * 64):
                    yield chunk

            return _iter_s3()
        except Exception:
            return None


def get_storage():
    """Factory that returns the configured storage adapter."""
    backend = (getattr(settings, "STORAGE_BACKEND", "local") or "local").lower()
    if backend in ("s3", "r2", "cloudflare"):
        return S3CompatibleStorage(
            endpoint_url=settings.STORAGE_ENDPOINT,
            bucket_name=settings.STORAGE_BUCKET,
            access_key=settings.STORAGE_ACCESS_KEY,
            secret_key=settings.STORAGE_SECRET_KEY,
            region=settings.STORAGE_REGION,
        )
    return LocalFileStorage()


class StorageProxy:
    """Dynamic proxy dispatching calls to the active storage backend."""

    def __getattr__(self, name):
        active_storage = get_storage()
        return getattr(active_storage, name)


storage = StorageProxy()
