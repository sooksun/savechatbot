from pathlib import Path
from datetime import datetime

import httpx

from ..config import get_settings

settings = get_settings()


def _content_url(message_id: str) -> str:
    return f"https://api-data.line.me/v2/bot/message/{message_id}/content"


async def download_line_content(message_id: str, ext: str = "jpg") -> str:
    """Download media from LINE Content API to local storage. Returns relative path."""
    root = Path(settings.MEDIA_ROOT)
    today = datetime.utcnow().strftime("%Y/%m/%d")
    target_dir = root / today
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{message_id}.{ext}"

    headers = {"Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(_content_url(message_id), headers=headers)
        r.raise_for_status()
        target.write_bytes(r.content)
    return str(target.relative_to(root))
