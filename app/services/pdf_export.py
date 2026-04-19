from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import markdown as md
from weasyprint import HTML, CSS

from ..config import get_settings

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
