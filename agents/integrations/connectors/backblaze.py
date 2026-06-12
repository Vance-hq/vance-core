"""Backblaze B2 connector — thin wrapper over shared/storage/client.py."""
from __future__ import annotations

import time
from typing import Any

from shared.logger import get_logger
from shared.storage.client import get_storage

from .base_connector import BaseConnector

logger = get_logger(__name__)


class BackblazeConnector(BaseConnector):
    service_name = "backblaze"
    _rate_limit_config = (0, 60)  # boto3 handles its own throttling

    @classmethod
    def load_credentials(cls) -> dict[str, str]:
        return {}  # credentials managed by shared/storage/client.py

    def _log_op(self, endpoint: str, status_code: int, latency_ms: int, error_msg: str | None = None) -> None:
        self._log(endpoint=endpoint, status_code=status_code, latency_ms=latency_ms, error_msg=error_msg)

    # ------------------------------------------------------------------

    def upload_file(
        self,
        data_bytes: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> dict:
        t0 = time.monotonic()
        try:
            url = get_storage().upload_bytes(data_bytes, key, content_type)
            self._log_op(f"/upload/{key}", 200, int((time.monotonic() - t0) * 1000))
            return {"url": url, "key": key, "bytes": len(data_bytes)}
        except Exception as exc:
            self._log_op(f"/upload/{key}", 0, int((time.monotonic() - t0) * 1000), str(exc))
            raise

    def download_file(self, key: str) -> dict:
        t0 = time.monotonic()
        try:
            import io
            storage = get_storage()
            obj = storage._client.get_object(Bucket=storage._bucket, Key=key)
            data = obj["Body"].read()
            self._log_op(f"/download/{key}", 200, int((time.monotonic() - t0) * 1000))
            return {"key": key, "data": data, "content_type": obj.get("ContentType", "application/octet-stream")}
        except Exception as exc:
            self._log_op(f"/download/{key}", 0, int((time.monotonic() - t0) * 1000), str(exc))
            raise

    def delete_file(self, key: str) -> dict:
        t0 = time.monotonic()
        try:
            storage = get_storage()
            storage._client.delete_object(Bucket=storage._bucket, Key=key)
            self._log_op(f"/delete/{key}", 204, int((time.monotonic() - t0) * 1000))
            return {"deleted": True, "key": key}
        except Exception as exc:
            self._log_op(f"/delete/{key}", 0, int((time.monotonic() - t0) * 1000), str(exc))
            raise

    def list_files(self, prefix: str = "", max_keys: int = 100) -> list[dict]:
        t0 = time.monotonic()
        try:
            storage = get_storage()
            resp = storage._client.list_objects_v2(
                Bucket=storage._bucket,
                Prefix=prefix,
                MaxKeys=max_keys,
            )
            objects = [
                {"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat()}
                for o in resp.get("Contents", [])
            ]
            self._log_op(f"/list/{prefix}", 200, int((time.monotonic() - t0) * 1000))
            return objects
        except Exception as exc:
            self._log_op(f"/list/{prefix}", 0, int((time.monotonic() - t0) * 1000), str(exc))
            raise

    def get_download_url(self, key: str) -> dict:
        from shared.config.settings import settings
        url = f"{settings.B2_ENDPOINT_URL}/file/{settings.B2_BUCKET_NAME}/{key}"
        return {"url": url, "key": key}

    def object_exists(self, key: str) -> dict:
        exists = get_storage().object_exists(key)
        return {"exists": exists, "key": key}
