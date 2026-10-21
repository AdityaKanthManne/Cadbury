#!/usr/bin/env python3
"""Desktop Butler backend entry point.

    python services/butler/butler_main.py            # API + 8 AM / 8 PM scheduler
    python services/butler/butler_main.py --once     # run one briefing and exit

The desktop app starts this automatically; you only run it by hand for debugging.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from butler.config import Profile, Settings  # noqa: E402


def setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(), RotatingFileHandler(settings.log_path, maxBytes=2_000_000, backupCount=3)):
        h.setFormatter(fmt)
        root.addHandler(h)


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Desktop Butler backend")
    ap.add_argument("--once", action="store_true", help="run a single briefing and exit")
    args = ap.parse_args()

    settings = Settings()
    setup_logging(settings)
    log = logging.getLogger("butler")
    profile = Profile.load()

    if args.once:
        from butler.db import Database
        from butler.service import ButlerService
        db = Database(settings.db_path)
        svc = ButlerService(settings, profile, db)
        result = svc.run_briefing("manual") or {}
        # plain summary for the terminal
        b = db.latest_briefing(successful_only=False)
        rows = db._query("SELECT source_type, COUNT(*) AS n FROM papers WHERE retrieved_at >= ? GROUP BY source_type",
                         (b["started_at"],)) if b else []
        print(f"\n  Briefing status: {result.get('status')}  ({result.get('fetched', 0)} results, {result.get('new_papers', 0)} new)")
        for r in rows:
            print(f"    {r['source_type']:<16} {r['n']:>4} new")
        m = db.latest_snapshot("markets")
        if m:
            print(f"    {'market prices':<16} {len(m['data']['rows']):>4} instruments")
        x = db.latest_snapshot("macro")
        if x:
            print(f"    {'FRED series':<16} {'needs key' if x['data'].get('needs_key') else len(x['data']['rows']):>4}")
        for e in result.get("errors") or []:
            print(f"    problem: {e['source'] if isinstance(e, dict) else ''} {e['error'] if isinstance(e, dict) else e}")
        return 0 if result.get("status") in ("ok", "partial") else 1

    if port_in_use(settings.host, settings.port):
        log.info("Backend already running on %s:%d — nothing to do", settings.host, settings.port)
        return 0

    import uvicorn
    from butler.api import create_app

    log.info("Desktop Butler backend on http://%s:%d (data: %s)", settings.host, settings.port, settings.data_dir)
    uvicorn.run(create_app(settings, profile), host=settings.host, port=settings.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
