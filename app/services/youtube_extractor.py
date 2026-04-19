"""YouTube transcript + Gemini summary. Uses yt-dlp to pull auto-captions."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from .gemini_client import _generate

log = logging.getLogger(__name__)

_VTT_CUE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*", re.MULTILINE)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_vtt(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    # Drop WEBVTT header, NOTE blocks, timing lines, and inline tags
    lines: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if _VTT_CUE_RE.search(line + " "):
            continue
        cleaned = _TAG_RE.sub("", line).strip()
        if cleaned and cleaned not in seen:
            lines.append(cleaned)
            seen.add(cleaned)
    return "\n".join(lines)


def fetch_transcript(url: str) -> str | None:
    """Download subtitles via yt-dlp, return plain text. Prefers Thai, falls back to English."""
    try:
        import yt_dlp
    except ImportError:
        log.warning("yt_dlp not installed")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["th", "en", "en-US", "en-GB"],
            "subtitlesformat": "vtt",
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            log.warning("yt_dlp failed: %s", e)
            return None

        vtt_files = sorted(Path(tmp).glob("*.vtt"))
        if not vtt_files:
            return None
        # Prefer Thai if present
        th = [f for f in vtt_files if ".th." in f.name]
        chosen = th[0] if th else vtt_files[0]
        try:
            return _clean_vtt(chosen) or None
        except Exception:
            return None


def summarize_transcript(transcript: str) -> str | None:
    if not transcript.strip():
        return None
    snippet = transcript[:30_000]
    prompt = (
        "สรุปเนื้อหาคลิป YouTube ต่อไปนี้เป็น Markdown ภาษาไทย\n"
        "โครงสร้าง:\n"
        "1. หัวข้อหลัก (1 บรรทัด)\n"
        "2. สรุปสั้น 3-5 บรรทัด\n"
        "3. ประเด็นสำคัญ (bullet 5-10 ข้อ)\n"
        "4. ศัพท์/บุคคล/แหล่งข้อมูลที่ถูกอ้างถึง (ถ้ามี)\n\n"
        f"ข้อความถอดเสียง:\n{snippet}"
    )
    return _generate(prompt)


def fetch_transcript_and_summary(url: str) -> tuple[str | None, str | None]:
    tr = fetch_transcript(url)
    if not tr:
        return None, None
    summary = summarize_transcript(tr)
    return tr, summary
