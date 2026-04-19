import re
from dataclasses import dataclass

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


@dataclass
class ExtractedLink:
    url: str
    kind: str  # youtube | google_drive | canva | other


def classify(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "drive.google.com" in u or "docs.google.com" in u:
        return "google_drive"
    if "canva.com" in u:
        return "canva"
    return "other"


def extract(text: str | None) -> list[ExtractedLink]:
    if not text:
        return []
    return [ExtractedLink(url=u, kind=classify(u)) for u in URL_RE.findall(text)]
