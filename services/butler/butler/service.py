"""Briefing orchestration + the 8 AM / 8 PM scheduler."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .collector import ArxivCollector
from .config import Profile, Settings
from .db import Database
from .ranking import Ranker, jaccard, select_briefing, title_tokens
from .sections import section_of
from .sources import SourceResult

log = logging.getLogger("butler.service")


NEWS_TYPES = ("news", "discussion", "lab_blog", "research_blog", "official")
CLUSTER_SIMILARITY = 0.55  # title overlap above which two headlines are the same story


def build_sources(profile: Profile, settings: Settings) -> List:
    """Instantiate the extra sources configured in user_profile.yaml (arXiv is separate)."""
    from .sources.gdelt import GdeltSource
    from .sources.hackernews import HackerNewsSource
    from .sources.markets import FredSource, MarketSource, fred_key
    from .sources.rss import RssSource

    cfg, out = profile.sources, []
    on = lambda k: (cfg.get(k) or {}).get("enabled", False)  # noqa: E731
    if on("rss"):
        c = cfg["rss"]
        out.append(RssSource(c.get("feeds", []), max_age_days=int(c.get("max_age_days", 7))))
    if on("gdelt"):
        c = cfg["gdelt"]
        out.append(GdeltSource(c.get("queries", []), timespan=c.get("timespan", "1d"), per_query=int(c.get("per_query", 25))))
    if on("hackernews"):
        c = cfg["hackernews"]
        out.append(HackerNewsSource(c.get("queries", []), min_points=int(c.get("min_points", 60)), days=int(c.get("days", 2))))
    if on("markets"):
        out.append(MarketSource(cfg["markets"].get("instruments", [])))
    if on("fred"):
        out.append(FredSource(cfg["fred"].get("series", []), fred_key(settings.data_dir)))
    return out


def cluster_stories(items: Dict[str, Dict], recent: List[Dict]) -> Tuple[Dict[str, Dict], Dict[str, List[str]]]:
    """Merge the same story reported by several outlets.

    Returns (items to store, {lead id: [extra outlets]}). The lead is the first copy seen,
    preferring top outlets; later copies only add their outlet to the lead's coverage.
    """
    leads: List[Tuple[str, frozenset]] = [(r["id"], title_tokens(r["title"])) for r in recent]
    keep: Dict[str, Dict] = {}
    merged: Dict[str, List[str]] = {}
    ordered = sorted(items.values(), key=lambda it: (not (it.get("meta") or {}).get("top_outlet"), it.get("published_at") or ""))
    for it in ordered:
        if it.get("source_type") not in ("news",):
            keep[it["id"]] = it
            continue
        toks = title_tokens(it["title"])
        match = next((lid for lid, lt in leads if jaccard(toks, lt) >= CLUSTER_SIMILARITY), None)
        if match:
            outlet = (it.get("meta") or {}).get("domain") or it.get("source")
            merged.setdefault(match, [])
            if outlet and outlet not in merged[match]:
                merged[match].append(outlet)
            continue
        keep[it["id"]] = it
        leads.append((it["id"], toks))
    return keep, merged


class ButlerService:
    def __init__(self, settings: Settings, profile: Profile, db: Database,
                 collector: Optional[ArxivCollector] = None, sources: Optional[List] = None):
        self.settings = settings
        self.profile = profile
        self.db = db
        # tests pass an arXiv collector and only the sources they want
        if sources is None:
            sources = [] if collector is not None else build_sources(profile, settings)
        self.collector = collector or ArxivCollector(profile.searches)
        self.sources = sources
        self.tz = ZoneInfo(settings.timezone)
        self._run_lock = threading.Lock()
        self.running_trigger: Optional[str] = None
        self.scheduler: Optional[BackgroundScheduler] = None

    def _collect_all(self) -> SourceResult:
        arx = self.collector.collect()
        res = SourceResult(items=dict(arx.papers), errors=list(arx.errors), fetched=arx.fetched)
        for src in self.sources:
            try:
                res.merge(src.collect())
            except Exception as e:  # a broken source must never take the briefing down
                log.exception("source %s crashed", type(src).__name__)
                res.errors.append({"source": type(src).__name__, "error": str(e)[:200]})
        return res

    # -- briefing -------------------------------------------------------
    def run_briefing(self, trigger: str = "manual") -> Optional[Dict]:
        """Fetch -> normalize -> dedupe -> rank -> select -> store. Thread-safe; skips if busy."""
        if not self._run_lock.acquire(blocking=False):
            log.info("Briefing already running; skipping %s trigger", trigger)
            return None
        self.running_trigger = trigger
        bid = self.db.start_briefing(trigger)
        try:
            log.info("Briefing #%d started (%s)", bid, trigger)
            res = self._collect_all()
            now = datetime.now(timezone.utc)

            # market and macro snapshots
            for kind in ("markets", "macro"):
                if kind in res.extra:
                    self.db.save_snapshot(kind, res.extra[kind]["taken_at"], res.extra[kind])

            # same story from several outlets -> one item with wider coverage
            three_days = (now - timedelta(days=3)).isoformat(timespec="seconds")
            recent_news = [r for r in self.db.recent_items(three_days, ("news",)) if r["id"] not in res.items]
            items, merged = cluster_stories(res.items, recent_news)
            for lead, outlets in merged.items():
                target = items.get(lead) or self.db.get_paper(lead)
                if not target:
                    continue
                meta = dict(target.get("meta") or {})
                meta["coverage"] = sorted(set(meta.get("coverage") or []) | set(outlets))
                if lead in items:
                    items[lead]["meta"] = meta
                else:
                    self.db.update_meta(lead, meta)

            new_ids = [pid for pid, p in items.items() if self.db.upsert_paper(p)]

            ranker = Ranker(self.profile)
            since = (now - timedelta(days=30)).isoformat(timespec="seconds")
            for pid in set(items) | {m for m in merged if m not in items}:
                paper = self.db.get_paper(pid)
                if not paper:
                    continue
                s = ranker.score(paper, self.db.recent_titles(pid, since))
                self.db.set_score(pid, s.area, s.score, s.breakdown, s.why, s.matched, section_of(paper, s.area))

            # Briefing pool: this run's items plus anything from the last 3 days
            # (keeps the butler useful when sources return little, e.g. weekends).
            pool = {p["id"]: p for p in self.db.list_papers(since=three_days, limit=1000)}
            for pid in items:
                pool.setdefault(pid, self.db.get_paper(pid))
            pool = {k: v for k, v in pool.items() if v and self.db.latest_feedback(k) != "not_relevant"}
            chosen = select_briefing(list(pool.values()), self.profile.briefing_size, self.profile.max_per_area,
                                     max_per_kind=self.profile.max_per_kind)
            item_ids = [p["id"] for p in chosen]

            if res.errors and not res.items and not res.extra.get("markets", {}).get("rows"):
                status = "failed"
            elif res.errors:
                status = "partial"
            else:
                status = "ok"
            self.db.finish_briefing(bid, status, res.fetched, len(new_ids), item_ids, res.errors)
            log.info("Briefing #%d %s: fetched=%d new=%d chosen=%d errors=%d",
                     bid, status, res.fetched, len(new_ids), len(item_ids), len(res.errors))
            return {"id": bid, "status": status, "fetched": res.fetched,
                    "new_papers": len(new_ids), "items": len(item_ids), "errors": res.errors}
        except Exception as e:
            log.exception("Briefing #%d crashed", bid)
            self.db.finish_briefing(bid, "failed", 0, 0, [], [{"source": "butler", "error": str(e)[:300]}])
            return {"id": bid, "status": "failed", "errors": [str(e)]}
        finally:
            self.running_trigger = None
            self._run_lock.release()

    def run_in_background(self, trigger: str) -> bool:
        if self._run_lock.locked():
            return False
        threading.Thread(target=self.run_briefing, args=(trigger,), daemon=True, name=f"briefing-{trigger}").start()
        return True

    # -- schedule -------------------------------------------------------
    def last_slot(self, now: Optional[datetime] = None) -> datetime:
        """Most recent scheduled time (8:00 or 20:00 Eastern) at or before now."""
        now = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        slots = []
        for day_offset in (0, -1):
            d = (now + timedelta(days=day_offset)).date()
            for h in self.settings.briefing_hours:
                slots.append(datetime(d.year, d.month, d.day, h, 0, tzinfo=self.tz))
        return max(s for s in slots if s <= now)

    def next_slots(self, n: int = 2, now: Optional[datetime] = None) -> List[datetime]:
        now = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        out = []
        for day_offset in range(0, 3):
            d = (now + timedelta(days=day_offset)).date()
            for h in sorted(self.settings.briefing_hours):
                s = datetime(d.year, d.month, d.day, h, 0, tzinfo=self.tz)
                if s > now:
                    out.append(s)
        return out[:n]

    def needs_catch_up(self, now: Optional[datetime] = None) -> bool:
        """True if a scheduled slot passed without a briefing (Mac asleep/off at 8:00)."""
        now = now or datetime.now(timezone.utc)
        slot = self.last_slot(now)
        ok = self.db.latest_briefing(successful_only=True)
        if ok and datetime.fromisoformat(ok["started_at"]) >= slot:
            return False
        tried = self.db.latest_briefing(successful_only=False)
        if tried and datetime.fromisoformat(tried["started_at"]) >= slot:
            # attempted since the slot but failed (e.g. offline): retry every 30 min
            return now - datetime.fromisoformat(tried["started_at"]) >= timedelta(minutes=30)
        return True

    def catch_up(self) -> None:
        if self.needs_catch_up():
            log.info("Missed a scheduled briefing; catching up now")
            self.run_in_background("catch-up")

    def start(self) -> None:
        self.db.fail_stale_running()
        if not self.settings.scheduler_enabled:
            log.info("Scheduler disabled (BUTLER_SCHEDULER=0)")
            return
        sched = BackgroundScheduler(timezone=self.tz)
        hours = ",".join(str(h) for h in self.settings.briefing_hours)
        sched.add_job(self.run_briefing, CronTrigger(hour=hours, minute=0, timezone=self.tz),
                      args=["scheduled"], id="briefing", coalesce=True, max_instances=1,
                      misfire_grace_time=3600)
        # laptops sleep through 8:00 — check every 15 min and catch up after wake
        sched.add_job(self.catch_up, IntervalTrigger(minutes=15), id="catch-up",
                      coalesce=True, max_instances=1)
        sched.start()
        self.scheduler = sched
        log.info("Scheduler started: briefings at %s:00 %s", hours, self.settings.timezone)
        self.catch_up()

    def stop(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            self.scheduler = None
