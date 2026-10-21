"""World news via the GDELT DOC 2.0 API (`gdeltdoc` library). Free, no key.

GDELT gives headlines and links, not article text, so these items are
`headline_only`: the butler never pretends to have read the article.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from . import SourceResult, base_item, item_id, short_error, strip_html

log = logging.getLogger("butler.gdelt")

# Outlets whose reporting gets a higher source-quality score.
TOP_OUTLETS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com", "economist.com",
    "apnews.com", "nytimes.com", "barrons.com", "marketwatch.com", "risk.net",
    "theinformation.com", "axios.com", "fortune.com",
}


def _seen(s: str) -> Optional[str]:
    """GDELT 'seendate' like 20261021T134500Z -> ISO UTC."""
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _default_search(keyword, timespan: str, num: int):
    """keyword: one term, or a list of terms that GDELT ORs together."""
    from gdeltdoc import Filters, GdeltDoc
    f = Filters(keyword=keyword, timespan=timespan, num_records=num, language="english")
    return GdeltDoc().article_search(f)


class GdeltSource:
    def __init__(self, queries: List, timespan: str = "1d", per_query: int = 25,
                 search: Optional[Callable] = None, pause: float = 5.0):
        self.queries = queries
        self.timespan = timespan
        self.per_query = per_query
        self.search = search or _default_search
        self.pause = pause  # GDELT asks for ~1 request per 5 s

    def collect(self) -> SourceResult:
        out = SourceResult()
        for i, q in enumerate(self.queries):
            if i:
                time.sleep(self.pause)
            label = ", ".join(q) if isinstance(q, (list, tuple)) else str(q)
            try:
                df = self.search(list(q) if isinstance(q, (list, tuple)) else q, self.timespan, self.per_query)
                rows = [] if df is None or len(df) == 0 else df.to_dict("records")
                for r in rows:
                    url, title = r.get("url"), strip_html(r.get("title"), 300)
                    if not url or not title or not str(url).startswith(("http://", "https://")):
                        continue
                    domain = (r.get("domain") or "").lower().removeprefix("www.")
                    iid = item_id("news", url)
                    if iid in out.items:
                        out.items[iid]["found_by"].append(label)
                        continue
                    out.items[iid] = base_item(
                        id=iid, title=title, published_at=_seen(r.get("seendate")),
                        url=url, source=domain or "news", source_type="news",
                        found_by=[label], meta={"domain": domain, "via": "GDELT",
                                            "country": r.get("sourcecountry"), "top_outlet": domain in TOP_OUTLETS},
                    )
                out.fetched += len(rows)
                log.info("GDELT '%s': %d articles", label, len(rows))
            except Exception as e:
                log.warning("GDELT '%s' failed: %s", label, e)
                out.errors.append(short_error(f"News: {label}", e))
        return out
