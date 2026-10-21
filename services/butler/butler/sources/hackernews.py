"""Hacker News stories via the free Algolia search API (httpx)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx

from . import SourceResult, USER_AGENT, base_item, short_error, strip_html

log = logging.getLogger("butler.hn")
API = "https://hn.algolia.com/api/v1/search"


class HackerNewsSource:
    def __init__(self, queries: List[str], min_points: int = 40, days: int = 2, per_query: int = 15,
                 client: Optional[httpx.Client] = None):
        self.queries = queries
        self.min_points = min_points
        self.days = days
        self.per_query = per_query
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})

    def collect(self) -> SourceResult:
        out = SourceResult()
        since = int((datetime.now(timezone.utc) - timedelta(days=self.days)).timestamp())
        for q in self.queries:
            try:
                resp = self.client.get(API, params={
                    "query": q, "tags": "story", "hitsPerPage": self.per_query,
                    "numericFilters": f"created_at_i>{since},points>={self.min_points}",
                })
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                for h in hits:
                    oid = str(h.get("objectID", ""))
                    title = strip_html(h.get("title"), 300)
                    if not oid or not title:
                        continue
                    discussion = f"https://news.ycombinator.com/item?id={oid}"
                    url = h.get("url") or discussion
                    iid = f"hn:{oid}"
                    if iid in out.items:
                        out.items[iid]["found_by"].append(q)
                        continue
                    created = h.get("created_at_i")
                    out.items[iid] = base_item(
                        id=iid, title=title, abstract=strip_html(h.get("story_text")),
                        authors=[h["author"]] if h.get("author") else [],
                        published_at=datetime.fromtimestamp(created, tz=timezone.utc).isoformat(timespec="seconds") if created else None,
                        url=url if url.startswith("https://") else discussion,
                        source="Hacker News", source_type="discussion", found_by=[q],
                        meta={"points": h.get("points") or 0, "comments": h.get("num_comments") or 0,
                              "discussion_url": discussion},
                    )
                out.fetched += len(hits)
                log.info("Hacker News '%s': %d stories", q, len(hits))
            except Exception as e:
                log.warning("Hacker News '%s' failed: %s", q, e)
                out.errors.append(short_error(f"Hacker News: {q}", e))
            time.sleep(0.3)
        return out
