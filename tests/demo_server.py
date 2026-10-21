"""Run the real backend against synthetic arXiv, news, Hacker News and market data (no network needed).

    python tests/demo_server.py [--port 8765] [--data /tmp/butler-demo]

For UI testing only: every paper it serves is synthetic test data.
"""

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "butler"))
sys.path.insert(0, str(ROOT / "tests"))

import uvicorn  # noqa: E402

from butler.api import create_app  # noqa: E402
from butler.collector import ArxivCollector  # noqa: E402
from butler.config import Profile, Settings  # noqa: E402
from butler.db import Database  # noqa: E402
from butler.service import ButlerService  # noqa: E402
from fake_arxiv import default_route, fake_client  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--data", default=tempfile.mkdtemp(prefix="butler-demo-"))
ap.add_argument("--no-seed", action="store_true")
args = ap.parse_args()

settings = Settings(data_dir=Path(args.data), port=args.port, scheduler_enabled=False)
profile = Profile.load()
client, _ = fake_client(default_route)
from test_sources import FEEDS, INSTR, RSS_ROUTES, fake_history, gdelt_frame, history_for, rss_client  # noqa: E402
import httpx  # noqa: E402
from butler.sources.gdelt import GdeltSource  # noqa: E402
from butler.sources.hackernews import HackerNewsSource  # noqa: E402
from butler.sources.markets import FredSource, MarketSource  # noqa: E402
from butler.sources.rss import RssSource  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

_now = int(datetime.now(timezone.utc).timestamp())
_seen = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
sources = [
    RssSource(FEEDS[:2], client=rss_client(RSS_ROUTES)),
    GdeltSource(["markets"], pause=0, search=lambda q, ts, n: gdelt_frame([
        ["https://www.reuters.com/test-fed", "", "Fed holds interest rates steady as inflation cools", _seen, "", "reuters.com", "English", "US"],
        ["https://www.cnbc.com/test-fed", "", "Fed holds interest rates steady as inflation cools further", _seen, "", "cnbc.com", "English", "US"],
        ["https://www.ft.com/test-hf", "", "Hedge fund bets on volatility as stock market swings", _seen, "", "ft.com", "English", "UK"],
    ])),
    HackerNewsSource(["quant"], client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": [
        {"objectID": "7", "title": "Show HN: limit order book simulator in Rust", "url": "https://github.com/example/lob",
         "points": 300, "num_comments": 90, "author": "c", "created_at_i": _now}]})))),
    MarketSource(INSTR[:2] + [{"ticker": "^VIX", "name": "VIX", "kind": "vol"}],
                 history=lambda t: history_for([15.1, 18.2]) if t == "^VIX" else fake_history(t)),
    FredSource([], api_key=None),
]
svc = ButlerService(settings, profile, Database(settings.db_path), ArxivCollector(profile.searches, client), sources=sources)
if not args.no_seed:
    print("seed:", svc.run_briefing("startup"))
uvicorn.run(create_app(settings, profile, svc, start_scheduler=False), host="127.0.0.1", port=args.port, log_level="warning")
