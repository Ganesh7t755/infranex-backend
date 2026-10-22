import os
import uuid
import shutil
from fastapi import UploadFile, HTTPException, status
from app.core.config import settings

ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

class LocalFileStorage:
    def __init__(self, upload_dir: str = settings.UPLOAD_DIR):
        self.upload_dir = upload_dir
        os.makedirs(self.upload_dir, exist_ok=True)

    def validate_file(self, file: UploadFile):
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type '{file.content_type}'. Allowed types: {list(ALLOWED_MIME_TYPES.keys())}"
            )

    def save_upload_sync(self, file: UploadFile) -> tuple[str, int]:
        self.validate_file(file)
        ext = ALLOWED_MIME_TYPES.get(file.content_type, ".jpg")
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

    def resolve_path(self, file_path: str) -> str | None:
        """Resolves file path whether stored as absolute or legacy relative path."""
        if file_path and os.path.exists(file_path):
            return file_path
        if file_path:
            fallback = os.path.join(self.upload_dir, os.path.basename(file_path))
            if os.path.exists(fallback):
                return fallback
        return None

storage = LocalFileStorage()
