"""Backblaze B2 storage client (S3-compatible via boto3)."""

from __future__ import annotations

import io
from functools import lru_cache

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class B2StorageClient:
    def __init__(self) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for B2 storage. Install it with: pip install boto3"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.B2_ENDPOINT_URL,
            aws_access_key_id=settings.B2_KEY_ID,
            aws_secret_access_key=settings.B2_APPLICATION_KEY,
        )
        self._bucket = settings.B2_BUCKET_NAME

    def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        """Upload bytes, return the public HTTPS URL."""
        self._client.upload_fileobj(
            io.BytesIO(data),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type, "ACL": "public-read"},
        )
        url = f"{settings.B2_ENDPOINT_URL}/file/{self._bucket}/{key}"
        logger.info("b2_upload_ok", key=key, bytes=len(data))
        return url

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False


@lru_cache(maxsize=1)
def get_storage() -> B2StorageClient:
    return B2StorageClient()


# Module-level alias for convenience.
# Imported as `from shared.storage.client import storage` in agent modules.
class _StorageProxy:
    """Defers B2StorageClient construction until first use, so imports don't fail without boto3."""

    def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        return get_storage().upload_bytes(data, key, content_type)

    def object_exists(self, key: str) -> bool:
        return get_storage().object_exists(key)


storage = _StorageProxy()
