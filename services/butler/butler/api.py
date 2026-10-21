"""Local HTTP API used by the desktop app. Bound to 127.0.0.1 only."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .config import Profile, Settings
from .db import Database
from .sections import SECTIONS
from .service import ButlerService

log = logging.getLogger("butler.api")

# Only the desktop app (and the Vite dev server) may call the API.
ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


class FeedbackIn(BaseModel):
    kind: Literal["relevant", "not_relevant", "opened", "dismissed"]


class BookmarkIn(BaseModel):
    on: bool


def public_paper(p: dict, db: Database) -> dict:
    return {
        "id": p["id"], "title": p["title"], "authors": p["authors"], "abstract": p["abstract"],
        "published_at": p["published_at"], "retrieved_at": p["retrieved_at"],
        "url": p["url"], "pdf_url": p["pdf_url"], "source": p["source"],
        "source_type": p["source_type"], "content_access": p["content_access"],
        "primary_category": p["primary_category"], "categories": p["categories"],
        "area": p["area"], "score": p["score"], "breakdown": p["breakdown"], "why": p["why"],
        "matched": p["matched"], "bookmarked": bool(p.get("bookmarked")),
        "meta": p.get("meta") or {},
        "section": p.get("section"),
        "feedback": db.latest_feedback(p["id"]),
    }


def greeting(owner: str, now: Optional[datetime] = None, tz=None) -> str:
    h = (now or datetime.now(tz)).hour
    part = "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"
    return f"{part}, {owner}." if owner else f"{part}."


def create_app(settings: Optional[Settings] = None, profile: Optional[Profile] = None,
               service: Optional[ButlerService] = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or Settings()
    profile = profile or Profile.load()
    if service is None:
        service = ButlerService(settings, profile, Database(settings.db_path))
    db = service.db

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_scheduler:
            service.start()
        yield
        service.stop()

    app = FastAPI(title="Desktop Butler", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    @app.get("/api/status")
    def status():
        last_ok = db.latest_briefing(successful_only=True)
        last_any = db.latest_briefing(successful_only=False)
        return {
            "collecting": service.running_trigger is not None,
            "collecting_trigger": service.running_trigger,
            "scheduler_running": service.scheduler is not None,
            "timezone": settings.timezone,
            "schedule": [f"{h:02d}:00" for h in settings.briefing_hours],
            "next_runs": [s.isoformat() for s in service.next_slots(2)],
            "last_success": last_ok,
            "last_attempt": last_any,
            "paper_count": db.count_papers(),
            "area_counts": db.area_counts(),
            "section_counts": db.section_counts(),
            "alert_threshold": profile.alert_threshold,
            "data_dir": str(settings.data_dir),
        }

    @app.get("/api/profile")
    def get_profile():
        return {
            "owner": profile.owner,
            "areas": [{"key": a.key, "label": a.label, "weight": a.weight, "keywords": a.keywords}
                      for a in profile.areas.values()],
            "searches": [{"name": s.name, "query": s.query, "max_results": s.max_results}
                         for s in profile.searches],
            "sections": [{"key": k, "label": label} for k, label in SECTIONS],
            "briefing_size": profile.briefing_size,
            "alert_threshold": profile.alert_threshold,
        }

    @app.post("/api/briefings/run", status_code=202)
    def run_now():
        started = service.run_in_background("manual")
        return {"started": started, "reason": None if started else "already collecting"}

    @app.get("/api/briefings/latest")
    def latest():
        b = db.latest_briefing(successful_only=True)
        tz = service.tz
        if not b:
            return {"briefing": None, "greeting": greeting(profile.owner, tz=tz), "items": []}
        items = [public_paper(p, db) for p in db.get_papers(b["item_ids"] or [])]
        return {"briefing": b, "greeting": greeting(profile.owner, tz=tz), "items": items,
                "alerts": [i["id"] for i in items if (i["score"] or 0) >= profile.alert_threshold]}

    @app.get("/api/briefings")
    def briefings(limit: int = Query(10, ge=1, le=100)):
        return db.recent_briefings(limit)

    @app.get("/api/papers")
    def papers(area: Optional[str] = None, q: Optional[str] = Query(None, max_length=200),
               sort: Literal["score", "date"] = "score", limit: int = Query(50, ge=1, le=500),
               bookmarked: bool = False, kind: Optional[Literal["papers", "news"]] = None,
               section: Optional[Literal["market", "research", "news", "tech"]] = None):
        return [public_paper(p, db) for p in db.list_papers(area, q, sort, limit, bookmarked, kind=kind, section=section)]

    @app.get("/api/markets")
    def markets():
        m, x = db.latest_snapshot("markets"), db.latest_snapshot("macro")
        return {
            "markets": m["data"] if m else None,
            "macro": x["data"] if x else None,
            "fred_enabled": bool((profile.sources.get("fred") or {}).get("enabled")),
        }

    @app.get("/api/papers/{paper_id}")
    def paper(paper_id: str):
        p = db.get_paper(paper_id)
        if not p:
            raise HTTPException(404, "paper not found")
        return public_paper(p, db)

    @app.post("/api/papers/{paper_id}/feedback")
    def feedback(paper_id: str, body: FeedbackIn):
        if not db.has_paper(paper_id):
            raise HTTPException(404, "paper not found")
        db.add_feedback(paper_id, body.kind)
        return {"ok": True}

    @app.post("/api/papers/{paper_id}/bookmark")
    def bookmark(paper_id: str, body: BookmarkIn):
        if not db.has_paper(paper_id):
            raise HTTPException(404, "paper not found")
        db.set_bookmark(paper_id, body.on)
        return {"ok": True, "bookmarked": body.on}

    @app.post("/api/personal-data/reset")
    def reset():
        db.reset_personal_data()
        return {"ok": True}

    return app
