from __future__ import annotations

import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import markdown as md
from weasyprint import HTML, CSS

from ..config import get_settings
from .minio_client import get_object_bytes

log = logging.getLogger(__name__)
settings = get_settings()

_HTML_TMPL = """<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;700&display=swap');
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font-family: 'Kanit', 'Sarabun', sans-serif; font-size: 12pt; color:#0f172a; line-height: 1.55; }}
  h1 {{ font-size: 20pt; margin: 0 0 4pt 0; color:#0b1220; }}
  h2 {{ font-size: 15pt; margin: 14pt 0 6pt; color:#1e293b; border-bottom: 1px solid #cbd5e1; padding-bottom:2pt; }}
  h3 {{ font-size: 13pt; margin: 10pt 0 4pt; color:#334155; }}
  ul, ol {{ margin: 4pt 0 8pt 0; padding-left: 18pt; }}
  li {{ margin: 2pt 0; }}
  p {{ margin: 4pt 0; }}
  .meta {{ color:#64748b; font-size: 10pt; margin-bottom: 14pt; }}
  hr {{ border:none; border-top:1px solid #cbd5e1; margin: 12pt 0; }}
  code {{ background:#f1f5f9; padding: 1pt 4pt; border-radius: 3pt; }}
  blockquote {{ border-left: 3pt solid #38bdf8; margin: 6pt 0; padding: 2pt 8pt; color:#475569; background:#f8fafc; }}
  table {{ border-collapse: collapse; width: 100%; margin: 6pt 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 4pt 6pt; text-align: left; }}
  th {{ background: #e2e8f0; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <div class="meta">กลุ่ม: {group_name} · สร้างเมื่อ {generated_at}</div>
  <hr/>
  {body_html}
</body>
</html>
"""


def summary_to_pdf(title: str, group_name: str, content_md: str) -> bytes:
    body_html = md.markdown(content_md or "", extensions=["extra", "sane_lists", "nl2br"])
    tz = ZoneInfo(settings.TIMEZONE)
    generated_at = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    html = _HTML_TMPL.format(
        title=title,
        group_name=group_name,
        generated_at=generated_at,
        body_html=body_html,
    )
    return HTML(string=html).write_pdf()


_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
}


def _media_to_data_uri(media_path: str) -> str | None:
    """MinIO object → base64 data URI so WeasyPrint can embed it without HTTP."""
    try:
        data = get_object_bytes(media_path)
    except Exception:
        log.exception("failed to fetch %s for PDF embed", media_path)
        return None
    ext = media_path.rsplit(".", 1)[-1].lower()
    mime = _MIME_BY_EXT.get(ext)
    if not mime:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


_SAR_CSS = """
  @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;500;700&display=swap');
  @page { size: A4; margin: 20mm 16mm 18mm 16mm; @bottom-center { content: counter(page) " / " counter(pages); font-family:'Kanit',sans-serif; font-size:9pt; color:#64748b; } }
  @page :first { @bottom-center { content: normal; } }
  body { font-family: 'Kanit', 'Sarabun', sans-serif; font-size: 12pt; color:#0f172a; line-height: 1.55; }
  .cover { text-align:center; padding-top:60mm; page-break-after: always; }
  .cover h1 { font-size: 32pt; margin: 0 0 8pt; color:#0b1220; }
  .cover .sub { font-size: 16pt; color:#475569; }
  .cover .year { font-size: 20pt; margin-top:30mm; color:#1e293b; }
  .toc { page-break-after: always; }
  .toc h2 { font-size: 18pt; border-bottom:2px solid #0f172a; padding-bottom:4pt; }
  .toc ul { list-style:none; padding:0; }
  .toc li { padding: 3pt 0; border-bottom: 1px dotted #cbd5e1; }
  h2.std { font-size: 16pt; margin: 16pt 0 6pt; color:#0b1220; border-bottom: 2pt solid #0ea5e9; padding-bottom:3pt; page-break-before: always; }
  h3 { font-size: 13pt; margin: 10pt 0 4pt; color:#334155; }
  .desc { color:#475569; margin-bottom: 10pt; font-size:11pt; }
  .evidence { margin: 8pt 0 14pt; }
  .ev-grid { display:flex; flex-wrap: wrap; gap: 6pt; margin: 4pt 0 8pt; }
  .ev-grid .thumb { width: 48%; border:1px solid #cbd5e1; padding:4pt; box-sizing:border-box; }
  .ev-grid .thumb img { width:100%; height:auto; display:block; }
  .ev-grid .cap { font-size: 9pt; color:#64748b; margin-top:2pt; }
  .ev-text { font-size:11pt; margin:3pt 0; padding:4pt 8pt; background:#f8fafc; border-left:3pt solid #0ea5e9; }
  .ev-link { font-size:10pt; color:#0369a1; }
  .empty { color:#94a3b8; font-style: italic; }
  ul { margin: 4pt 0 8pt 0; padding-left: 18pt; }
"""


def _evidence_html(evidences: list[dict]) -> str:
    """evidences: [{type, text, thumb_uri, caption, link_url, link_title}]"""
    if not evidences:
        return '<div class="empty">— ยังไม่มีหลักฐาน —</div>'
    images = [e for e in evidences if e.get("thumb_uri")]
    texts = [e for e in evidences if e.get("text") and not e.get("thumb_uri") and not e.get("link_url")]
    links = [e for e in evidences if e.get("link_url")]

    parts: list[str] = []
    if images:
        parts.append('<h3>รูปภาพหลักฐาน</h3>')
        parts.append('<div class="ev-grid">')
        for e in images:
            caption = (e.get("caption") or "").replace("<", "&lt;")[:200]
            parts.append(
                f'<div class="thumb"><img src="{e["thumb_uri"]}"/>'
                f'<div class="cap">{caption}</div></div>'
            )
        parts.append('</div>')
    if texts:
        parts.append('<h3>บันทึกข้อความ</h3>')
        for e in texts:
            body = (e["text"] or "").replace("<", "&lt;")[:1000]
            parts.append(f'<div class="ev-text">{body}</div>')
    if links:
        parts.append('<h3>ลิงก์อ้างอิง</h3><ul>')
        for e in links:
            title = (e.get("link_title") or e["link_url"]).replace("<", "&lt;")[:200]
            parts.append(f'<li class="ev-link">{title} — {e["link_url"]}</li>')
        parts.append('</ul>')
    return "\n".join(parts)


def sar_book_to_pdf(
    title: str,
    year: str,
    sections: list[dict],
) -> bytes:
    """sections: [{code, title, description, evidences: [...]}]

    If len(sections) == 1 the output is a single-standard booklet (no cover/TOC).
    """
    tz = ZoneInfo(settings.TIMEZONE)
    generated_at = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    body: list[str] = []
    single = len(sections) == 1

    if not single:
        body.append(
            f'<div class="cover"><h1>{title}</h1>'
            f'<div class="sub">รายงานการประเมินตนเองของสถานศึกษา (SAR)</div>'
            f'<div class="year">ปีการศึกษา {year}</div>'
            f'<div class="sub" style="margin-top:20mm;font-size:11pt">สร้างเมื่อ {generated_at}</div></div>'
        )
        body.append('<div class="toc"><h2>สารบัญ</h2><ul>')
        for s in sections:
            body.append(f'<li>มาตรฐานที่ {s["code"]} — {s["title"]}</li>')
        body.append("</ul></div>")

    for s in sections:
        desc = (s.get("description") or "").replace("<", "&lt;")
        body.append(
            f'<h2 class="std">มาตรฐานที่ {s["code"]} — {s["title"]}</h2>'
            f'<div class="desc">{desc}</div>'
            f'<div class="evidence">{_evidence_html(s.get("evidences", []))}</div>'
        )

    html = (
        '<!doctype html><html lang="th"><head><meta charset="utf-8"/>'
        f'<title>{title}</title><style>{_SAR_CSS}</style></head>'
        f'<body>{"".join(body)}</body></html>'
    )
    return HTML(string=html).write_pdf()
