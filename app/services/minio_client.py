from __future__ import annotations

import io
import logging
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from ..config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_minio() -> Minio:
    s = get_settings()
    return Minio(
        s.MINIO_ENDPOINT,
        access_key=s.MINIO_ACCESS_KEY,
        secret_key=s.MINIO_SECRET_KEY,
        secure=s.MINIO_SECURE,
    )


def ensure_bucket() -> None:
    s = get_settings()
    client = get_minio()
    try:
        if not client.bucket_exists(s.MINIO_BUCKET):
            client.make_bucket(s.MINIO_BUCKET)
            log.info("Created MinIO bucket: %s", s.MINIO_BUCKET)
    except S3Error as e:
        log.error("MinIO bucket check failed: %s", e)


def upload_bytes(object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to MinIO. Returns the object name (used as media_path)."""
    s = get_settings()
    client = get_minio()
    client.put_object(
        s.MINIO_BUCKET,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_name


def get_presigned_url(object_name: str, expires_seconds: int = 3600) -> str:
    from datetime import timedelta
    s = get_settings()
    client = get_minio()
    return client.presigned_get_object(
        s.MINIO_BUCKET,
        object_name,
        expires=timedelta(seconds=expires_seconds),
    )


def get_object_stream(object_name: str):
    """Return MinIO response object (caller must close). Use for streaming."""
    s = get_settings()
    client = get_minio()
    return client.get_object(s.MINIO_BUCKET, object_name)


def stat_object(object_name: str):
    s = get_settings()
    client = get_minio()
    return client.stat_object(s.MINIO_BUCKET, object_name)
