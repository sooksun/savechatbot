from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from ..config import get_settings
from .minio_client import upload_bytes

settings = get_settings()

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/plain": "txt",
    "text/csv": "csv",
}

_MIME_CLEAN: dict[str, str] = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "pdf": "application/pdf",
    "zip": "application/zip",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "csv": "text/csv",
}

_CD_FILENAME_RE = re.compile(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\r\n]+)', re.IGNORECASE)


def _ext_from_headers(headers: httpx.Headers, fallback: str) -> tuple[str, str | None]:
    original_filename: str | None = None

    cd = headers.get("content-disposition", "")
    if cd:
        m = _CD_FILENAME_RE.search(cd)
        if m:
            from urllib.parse import unquote
            original_filename = unquote(m.group(1).strip().strip('"\''))
            suffix = Path(original_filename).suffix.lstrip(".")
            if suffix:
                return suffix.lower(), original_filename

    ct = headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _MIME_TO_EXT.get(ct, fallback)
    return ext, original_filename


def _content_url(message_id: str) -> str:
    return f"https://api-data.line.me/v2/bot/message/{message_id}/content"


@dataclass
class DownloadResult:
    relative_path: str   # MinIO object name
    original_filename: str | None
    ext: str


async def download_line_content(message_id: str, fallback_ext: str = "jpg") -> DownloadResult:
    """Download media from LINE Content API and upload to MinIO."""
    auth_headers = {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(_content_url(message_id), headers=auth_headers)
        r.raise_for_status()

        ext, original_filename = _ext_from_headers(r.headers, fallback_ext)
        ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
        content_type = ct if ct else _MIME_CLEAN.get(ext, "application/octet-stream")

        today = datetime.utcnow().strftime("%Y/%m/%d")
        object_name = f"{today}/{message_id}.{ext}"
        upload_bytes(object_name, r.content, content_type)

    return DownloadResult(
        relative_path=object_name,
        original_filename=original_filename,
        ext=ext,
    )
