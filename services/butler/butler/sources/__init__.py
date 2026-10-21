"""Data sources. Each collector returns a SourceResult; one failing source never stops the others.

Every item uses the same shape as an arXiv paper (see collector.normalize), with
`source_type` telling them apart:

    academic_paper   arXiv
    official         central banks, regulators (RSS)
    research_blog    quant firms' engineering/research blogs (RSS)
    lab_blog         AI labs' blogs (RSS)
    news             news outlets (GDELT, news RSS)
    discussion       Hacker News
    market_move      a notable move computed from market data (yfinance)
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..collector import clean

USER_AGENT = "DesktopButler/0.3 (personal research assistant; +https://github.com/AdityaKanthManne/Cadbury)"

_TAG = re.compile(r"<[^>]+>")


@dataclass
class SourceResult:
    items: Dict[str, Dict] = field(default_factory=dict)
    errors: List[Dict[str, str]] = field(default_factory=list)
    fetched: int = 0
    extra: Dict = field(default_factory=dict)  # e.g. market snapshot

    def merge(self, other: "SourceResult") -> None:
        for k, v in other.items.items():
            self.items.setdefault(k, v)
        self.errors += other.errors
        self.fetched += other.fetched
        self.extra.update(other.extra)


def item_id(prefix: str, key: str) -> str:
    return f"{prefix}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def strip_html(text: Optional[str], limit: int = 1200) -> str:
    """Feed summaries are HTML from the open web: drop tags, unescape, collapse, cap."""
    if not text:
        return ""
    t = clean(html.unescape(_TAG.sub(" ", text)))
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_error(source: str, e: Exception) -> Dict[str, str]:
    msg = str(e)
    if "403" in msg and ("proxy" in msg.lower() or "Proxy" in type(e).__name__):
        text = "Network blocked (403). Check internet/VPN."
    elif any(s in msg for s in ("timed out", "Timeout", "ConnectTimeout")):
        text = "Timed out."
    elif any(s in type(e).__name__ for s in ("ConnectError", "ConnectionError")):
        text = "Could not connect (offline or service down)."
    else:
        text = f"{type(e).__name__}: {msg[:200]}"
    return {"source": source, "error": text}


def base_item(**kw) -> Dict:
    item = {
        "version": None, "authors": [], "abstract": "", "updated_at": None, "pdf_url": None,
        "primary_category": None, "categories": [], "journal_ref": None, "comment": None,
        "content_access": "headline_only", "found_by": [], "meta": {},
        "retrieved_at": now_iso(),
    }
    item.update(kw)
    return item
