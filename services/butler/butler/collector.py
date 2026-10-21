"""arXiv ingestion through the official `arxiv` Python library."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import arxiv

from .config import ArxivSearchSpec
from .db import utcnow

log = logging.getLogger("butler.collector")

_VERSION_RE = re.compile(r"v(\d+)$")
_WS = re.compile(r"\s+")


_ACCENTS = {"'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303", "c": "\u0327", "v": "\u030c"}
_LATEX_ACCENT = re.compile(r"""\\([`'"^~]|[cv](?=\s|\{))\s*\{?\\?([A-Za-z])\}?""")


def _delatex(text: str) -> str:
    """arXiv metadata spells accents in LaTeX: L\\'evy -> Lévy, K\\"ock -> Köck."""
    import unicodedata
    out = _LATEX_ACCENT.sub(lambda m: unicodedata.normalize("NFC", m.group(2) + _ACCENTS[m.group(1)]), text)
    return out.replace("{", "").replace("}", "") if "\\" not in out else out


def clean(text: Optional[str]) -> str:
    """Retrieved text is untrusted: collapse whitespace, strip control chars, decode LaTeX accents."""
    if not text:
        return ""
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return _WS.sub(" ", _delatex(text)).strip()


def split_id(entry_id: str) -> tuple[str, Optional[str]]:
    """'http://arxiv.org/abs/2410.01234v2' -> ('2410.01234', 'v2')."""
    short = entry_id.rsplit("/abs/", 1)[-1]
    m = _VERSION_RE.search(short)
    if m:
        return short[: m.start()], "v" + m.group(1)
    return short, None


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize(result: "arxiv.Result", search_name: str) -> Dict:
    pid, version = split_id(result.entry_id)
    return {
        "id": pid,
        "version": version,
        "title": clean(result.title),
        "authors": [clean(a.name) for a in result.authors],
        "abstract": clean(result.summary),
        "published_at": iso(result.published),
        "updated_at": iso(result.updated),
        "retrieved_at": utcnow(),
        "url": f"https://arxiv.org/abs/{pid}",
        "pdf_url": result.pdf_url,
        "primary_category": result.primary_category,
        "categories": list(result.categories or []),
        "journal_ref": clean(result.journal_ref) or None,
        "comment": clean(result.comment) or None,
        "source": "arXiv",
        "source_type": "academic_paper",
        "content_access": "abstract_only",
        "found_by": [search_name],
        "meta": {},
    }


@dataclass
class CollectResult:
    papers: Dict[str, Dict] = field(default_factory=dict)  # id -> normalized paper (deduped)
    errors: List[Dict[str, str]] = field(default_factory=list)
    fetched: int = 0


class ArxivCollector:
    def __init__(self, searches: List[ArxivSearchSpec], client: Optional[arxiv.Client] = None):
        self.searches = searches
        # arXiv asks for >= 3 s between requests; the library enforces it.
        self.client = client or arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)

    def collect(self) -> CollectResult:
        out = CollectResult()
        for spec in self.searches:
            try:
                # ask arXiv for only as many results as this search needs
                self.client.page_size = max(1, min(spec.max_results, 100))
                search = arxiv.Search(
                    query=spec.query,
                    max_results=spec.max_results,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                )
                n = 0
                for result in self.client.results(search):
                    paper = normalize(result, spec.name)
                    n += 1
                    if paper["id"] in out.papers:  # dedupe across searches by arXiv id
                        found = out.papers[paper["id"]]["found_by"]
                        if spec.name not in found:
                            found.append(spec.name)
                    else:
                        out.papers[paper["id"]] = paper
                out.fetched += n
                log.info("arXiv '%s': %d results", spec.name, n)
            except Exception as e:  # one failing search must not kill the briefing
                log.warning("arXiv '%s' failed: %s", spec.name, e)
                out.errors.append({"source": f"arXiv: {spec.name}", "error": _short_error(e)})
        return out


def _short_error(e: Exception) -> str:
    msg = str(e)
    if "403" in msg and "proxy" in msg.lower():
        return "Network blocked by proxy (403). Check internet/VPN."
    if "Max retries" in msg or "ConnectionError" in type(e).__name__:
        return "Could not reach arXiv (offline or arXiv down)."
    return f"{type(e).__name__}: {msg[:200]}"
