"""Thin wrapper around google-genai for classification + summarization.

We avoid hard-failing if the API is unavailable — callers should tolerate None.
"""
from __future__ import annotations

import json
from typing import Iterable

from google import genai
from google.genai import types

from ..config import get_settings

settings = get_settings()

_client: genai.Client | None = None


def _get_client() -> genai.Client | None:
    global _client
    if not settings.GEMINI_API_KEY:
        return None
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _generate(prompt: str, *, response_mime_type: str | None = None) -> str | None:
    client = _get_client()
    if client is None:
        return None
    config = types.GenerateContentConfig(
        temperature=0.3,
        response_mime_type=response_mime_type,
    )
    resp = client.models.generate_content(
        model=settings.GEMINI_MODEL, contents=prompt, config=config
    )
    return (resp.text or "").strip()


def classify_message(text: str, categories: list[str]) -> str | None:
    """Return one of the provided category names, or a new short label if none fit."""
    if not text.strip():
        return None
    cats = "\n".join(f"- {c}" for c in categories)
    prompt = (
        "คุณคือผู้ช่วยจัดหมวดหมู่ข้อความแชททีมงานภาษาไทย\n"
        "เลือกหมวดที่ตรงที่สุดจากรายการต่อไปนี้ หรือถ้าไม่มีหมวดใดเหมาะ ให้เสนอชื่อหมวดใหม่ "
        "สั้นๆ (<=20 ตัวอักษร) ตอบเป็น JSON เท่านั้น\n\n"
        f"หมวดที่มี:\n{cats}\n\n"
        f"ข้อความ: \"\"\"{text}\"\"\"\n\n"
        'รูปแบบตอบ: {"category": "<ชื่อหมวด>", "is_new": true|false}'
    )
    raw = _generate(prompt, response_mime_type="application/json")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        name = (data.get("category") or "").strip()
        return name or None
    except json.JSONDecodeError:
        return None


def ocr_image(data: bytes, mime_type: str = "image/jpeg") -> str | None:
    """Extract readable text from image bytes using Gemini. Returns None on failure."""
    client = _get_client()
    if client is None:
        return None
    if not data:
        return None
    prompt = (
        "สกัดข้อความทั้งหมดที่อ่านได้ในรูปภาพนี้ (ภาษาไทย/อังกฤษ) "
        "ตอบเฉพาะตัวข้อความ ไม่ต้องอธิบาย ถ้าไม่มีข้อความให้ตอบว่า NONE"
    )
    try:
        resp = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
    except Exception:
        return None
    text = (resp.text or "").strip()
    if not text or text.upper() == "NONE":
        return None
    return text[:5000]


def summarize_conversations(
    lines: Iterable[str], *, period_label: str
) -> str | None:
    """Produce a markdown summary grouped by topic for the given lines."""
    joined = "\n".join(lines)
    if not joined.strip():
        return None
    prompt = (
        f"คุณคือผู้ช่วยสรุปบทสนทนาของทีมงานในกลุ่ม LINE\n"
        f"สรุปเป็น Markdown ภาษาไทย สำหรับช่วง: {period_label}\n"
        "โครงสร้างที่ต้องการ:\n"
        "1. ภาพรวม (2-4 บรรทัด)\n"
        "2. หัวข้อสำคัญ (แยกเป็นหัวข้อย่อย พร้อม bullet)\n"
        "3. การตัดสินใจ / งานที่มอบหมาย (ถ้ามี)\n"
        "4. ลิงก์ทรัพยากรที่ถูกแชร์ (YouTube / Google Drive / Canva / อื่นๆ)\n"
        "5. สิ่งที่ต้องติดตามต่อ\n\n"
        "ข้อมูลบทสนทนา (บรรทัดละข้อความ รูปแบบ [เวลา] ผู้พูด: ข้อความ):\n"
        f"{joined}"
    )
    return _generate(prompt)
