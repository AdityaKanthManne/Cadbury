"""RSS/Atom feeds (Federal Reserve, quant firms, AI labs) via feedparser."""

from __future__ import annotations

import calendar
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import feedparser
import httpx

from . import SourceResult, USER_AGENT, base_item, item_id, short_error, strip_html

log = logging.getLogger("butler.rss")


def _entry_time(e) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = e.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


class RssSource:
    """feeds: [{name, url, kind}] where kind is official | research_blog | lab_blog | news."""

    def __init__(self, feeds: List[Dict], max_age_days: int = 7, per_feed: int = 15,
                 client: Optional[httpx.Client] = None):
        self.feeds = feeds
        self.max_age = timedelta(days=max_age_days)
        self.per_feed = per_feed
        self.client = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT})

    def collect(self) -> SourceResult:
        out = SourceResult()
        cutoff = datetime.now(timezone.utc) - self.max_age
        for feed in self.feeds:
            name = feed["name"]
            try:
                resp = self.client.get(feed["url"])
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(f"not a valid feed ({parsed.bozo_exception})")
                n = 0
                for e in parsed.entries[: self.per_feed]:
                    link = e.get("link") or e.get("id")
                    title = strip_html(e.get("title"), 300)
                    if not link or not title or not link.startswith(("http://", "https://")):
                        continue
                    when = _entry_time(e)
                    if when and when < cutoff:
                        continue  # old back-catalogue
                    summary = strip_html(e.get("summary") or (e.get("content") or [{}])[0].get("value"))
                    author = e.get("author")
                    out.items[item_id("rss", link)] = base_item(
                        id=item_id("rss", link), title=title, abstract=summary,
                        authors=[strip_html(author, 120)] if author else [],
                        published_at=when.isoformat(timespec="seconds") if when else None,
                        url=link.replace("http://", "https://", 1), source=name,
                        source_type=feed.get("kind", "news"),
                        content_access="summary" if summary else "headline_only",
                        found_by=[name], meta={"feed": name},
                    )
                    n += 1
                out.fetched += n
                log.info("RSS '%s': %d recent items", name, n)
            except Exception as e:
                log.warning("RSS '%s' failed: %s", name, e)
                out.errors.append(short_error(f"RSS: {name}", e))
            time.sleep(0.2)
        return out
