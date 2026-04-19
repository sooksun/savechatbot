"""Gemini embeddings + Qdrant vector store for semantic search."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from ..config import get_settings
from ..models import Link, Message
from .gemini_client import _get_client

log = logging.getLogger(__name__)
settings = get_settings()


@lru_cache
def get_qdrant() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL, timeout=10)


def ensure_collection() -> None:
    client = get_qdrant()
    try:
        collections = {c.name for c in client.get_collections().collections}
        if settings.QDRANT_COLLECTION not in collections:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=qm.VectorParams(size=settings.EMBED_DIM, distance=qm.Distance.COSINE),
            )
            log.info("Created Qdrant collection: %s", settings.QDRANT_COLLECTION)
    except Exception:
        log.exception("ensure_collection failed")


def embed(text: str) -> list[float] | None:
    text = (text or "").strip()
    if not text:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.models.embed_content(model=settings.EMBED_MODEL, contents=text[:8000])
        embs = resp.embeddings or []
        if not embs:
            return None
        return list(embs[0].values)
    except Exception:
        log.exception("embed failed")
        return None


def _message_text(m: Message) -> str:
    parts: list[str] = []
    if m.text:
        parts.append(m.text)
    if m.ocr_text:
        parts.append(f"[OCR]\n{m.ocr_text}")
    if m.doc_text:
        parts.append(f"[DOC]\n{m.doc_text[:6000]}")
    for ln in m.links or []:
        if ln.summary:
            parts.append(f"[VIDEO SUMMARY]\n{ln.summary}")
    return "\n\n".join(parts)


def embed_message(m: Message) -> None:
    body = _message_text(m)
    if not body:
        return
    vec = embed(body)
    if not vec:
        return
    payload = {
        "message_id": m.id,
        "group_id": m.group_id,
        "user_id": m.user_id,
        "msg_type": m.msg_type,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "preview": body[:500],
    }
    try:
        get_qdrant().upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[qm.PointStruct(id=m.id, vector=vec, payload=payload)],
        )
    except Exception:
        log.exception("qdrant upsert failed for message %s", m.id)


def search(
    query: str,
    *,
    group_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    vec = embed(query)
    if not vec:
        return []
    flt = None
    if group_id is not None:
        flt = qm.Filter(must=[qm.FieldCondition(key="group_id", match=qm.MatchValue(value=group_id))])
    try:
        hits = get_qdrant().search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vec,
            query_filter=flt,
            limit=limit,
        )
    except Exception:
        log.exception("qdrant search failed")
        return []
    return [
        {"message_id": h.payload.get("message_id"), "score": h.score, "payload": h.payload}
        for h in hits
    ]
