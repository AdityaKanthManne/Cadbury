import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "butler"))
sys.path.insert(0, str(ROOT / "tests"))

from butler.collector import ArxivCollector  # noqa: E402
from butler.config import Profile, Settings  # noqa: E402
from butler.db import Database  # noqa: E402
from butler.service import ButlerService  # noqa: E402
from fake_arxiv import default_route, fake_client  # noqa: E402


@pytest.fixture
def profile():
    return Profile.load(ROOT / "configs" / "user_profile.yaml")


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, scheduler_enabled=False)


@pytest.fixture
def db(settings):
    d = Database(settings.db_path)
    yield d
    d.close()


@pytest.fixture
def make_service(settings, profile, db):
    def _make(route=default_route):
        client, adapter = fake_client(route)
        svc = ButlerService(settings, profile, db, ArxivCollector(profile.searches, client))
        svc.adapter = adapter
        return svc
    return _make


@pytest.fixture
def full_service(settings, profile, db):
    """Every source wired up, with all network traffic simulated."""
    import httpx
    from butler.sources.gdelt import GdeltSource
    from butler.sources.hackernews import HackerNewsSource
    from butler.sources.markets import FredSource, MarketSource
    from butler.sources.rss import RssSource
    from test_sources import FEEDS, INSTR, NOW, RSS_ROUTES, fake_history, gdelt_frame, rss_client
    client, _ = fake_client(default_route)
    gd = GdeltSource(["markets"], search=lambda q, ts, n: gdelt_frame([
        ["https://www.reuters.com/fed", "", "Fed holds interest rates steady as inflation cools", "20261021T140000Z", "", "reuters.com", "English", "US"],
        ["https://www.cnbc.com/fed", "", "Fed holds interest rates steady as inflation cools further", "20261021T141000Z", "", "cnbc.com", "English", "US"],
    ]), pause=0)
    hn = HackerNewsSource(["quant"], client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": [
        {"objectID": "7", "title": "Show HN: limit order book simulator in Rust", "url": "https://github.com/x/lob",
         "points": 300, "num_comments": 90, "author": "c", "created_at_i": int(NOW.timestamp())}]}))))
    sources = [RssSource(FEEDS, client=rss_client(RSS_ROUTES)), gd, hn, MarketSource(INSTR, history=fake_history),
               FredSource([], api_key=None)]
    return ButlerService(settings, profile, db, ArxivCollector(profile.searches, client), sources=sources)


