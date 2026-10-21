"""News, discussion and market sources, with every network call simulated (synthetic data)."""

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from butler.api import create_app
from butler.collector import ArxivCollector
from butler.ranking import Ranker
from butler.service import ButlerService, cluster_stories
from butler.sources.gdelt import GdeltSource
from butler.sources.hackernews import HackerNewsSource
from butler.sources.markets import FredSource, MarketSource, fred_key
from butler.sources.rss import RssSource
from fake_arxiv import default_route, fake_client

NOW = datetime.now(timezone.utc)
rfc822 = lambda d: d.strftime("%a, %d %b %Y %H:%M:%S +0000")  # noqa: E731

FED_RSS = f"""<?xml version="1.0"?><rss version="2.0"><channel><title>FRB: Press Release</title>
<item><title>Federal Reserve issues FOMC statement</title><link>https://www.federalreserve.gov/newsevents/pressreleases/monetary-test.htm</link>
<description>&lt;p&gt;The Committee decided to &lt;b&gt;maintain&lt;/b&gt; the target range for the federal funds rate.&lt;/p&gt;</description>
<pubDate>{rfc822(NOW - timedelta(hours=5))}</pubDate></item>
<item><title>Old release from last year</title><link>https://www.federalreserve.gov/old.htm</link>
<pubDate>{rfc822(NOW - timedelta(days=300))}</pubDate></item>
<item><title>Bad link item</title><link>javascript:alert(1)</link><pubDate>{rfc822(NOW)}</pubDate></item>
</channel></rss>"""

LAB_ATOM = f"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Lab Blog</title>
<entry><title>A new open-source time-series foundation model</title><link href="https://lab.example/blog/tsfm"/>
<id>tag:lab.example,2026:tsfm</id><updated>{(NOW - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}</updated>
<summary>We release weights and code for a transformer forecasting model.</summary><author><name>Lab Team</name></author></entry>
</feed>"""


def rss_client(routes):
    def handler(req: httpx.Request):
        body = routes.get(str(req.url))
        if body is None:
            return httpx.Response(500)
        return httpx.Response(200, content=body.encode())
    return httpx.Client(transport=httpx.MockTransport(handler))


FEEDS = [
    {"name": "Federal Reserve press releases", "url": "https://fed.test/press.xml", "kind": "official"},
    {"name": "Lab Blog", "url": "https://lab.test/feed.xml", "kind": "lab_blog"},
    {"name": "Broken Feed", "url": "https://broken.test/feed.xml", "kind": "news"},
]
RSS_ROUTES = {"https://fed.test/press.xml": FED_RSS, "https://lab.test/feed.xml": LAB_ATOM}


# ---- RSS -----------------------------------------------------------------------
def test_rss_parses_filters_and_isolates_failures():
    res = RssSource(FEEDS, client=rss_client(RSS_ROUTES)).collect()
    titles = {i["title"]: i for i in res.items.values()}
    assert set(titles) == {"Federal Reserve issues FOMC statement", "A new open-source time-series foundation model"}
    fed = titles["Federal Reserve issues FOMC statement"]
    assert fed["source_type"] == "official" and fed["source"] == "Federal Reserve press releases"
    assert fed["abstract"] == "The Committee decided to maintain the target range for the federal funds rate."  # HTML stripped
    assert fed["url"].startswith("https://") and fed["content_access"] == "summary"
    assert titles["A new open-source time-series foundation model"]["authors"] == ["Lab Team"]
    assert [e["source"] for e in res.errors] == ["RSS: Broken Feed"]


# ---- GDELT ---------------------------------------------------------------------
def gdelt_frame(rows):
    return pd.DataFrame(rows, columns=["url", "url_mobile", "title", "seendate", "socialimage", "domain", "language", "sourcecountry"])


def test_gdelt_normalizes_and_dedupes():
    def search(q, timespan, num):
        if "fail" in q:
            raise httpx.ConnectError("down")
        return gdelt_frame([
            ["https://www.reuters.com/markets/fed-holds", "", "Fed holds rates steady as inflation cools", "20261021T140000Z", "", "reuters.com", "English", "US"],
            ["https://smallblog.example/fed", "", "Fed holds rates steady", "20261021T150000Z", "", "smallblog.example", "English", "US"],
        ])
    res = GdeltSource(["fed", ["fed again", "rates"], "fail query"], search=search, pause=0).collect()
    assert len(res.items) == 2 and res.fetched == 4
    reuters = next(i for i in res.items.values() if i["meta"]["domain"] == "reuters.com")
    assert reuters["meta"]["top_outlet"] and reuters["published_at"] == "2026-10-21T14:00:00+00:00"
    assert reuters["found_by"] == ["fed", "fed again, rates"] and reuters["content_access"] == "headline_only"
    assert res.errors[0]["source"] == "News: fail query"


# ---- Hacker News -----------------------------------------------------------------
def test_hackernews_query_and_items():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"hits": [
            {"objectID": "101", "title": "Show HN: vectorized backtester in JAX", "url": "https://github.com/x/bt",
             "points": 420, "num_comments": 130, "author": "alice", "created_at_i": int(NOW.timestamp()) - 3600},
            {"objectID": "102", "title": "Ask HN: quant interview prep?", "url": None, "points": 80,
             "num_comments": 50, "author": "bob", "created_at_i": int(NOW.timestamp()) - 7200},
        ]})
    res = HackerNewsSource(["quant"], min_points=60, client=httpx.Client(transport=httpx.MockTransport(handler))).collect()
    assert "points>=60" in seen["numericFilters"] and seen["tags"] == "story"
    a, b = res.items["hn:101"], res.items["hn:102"]
    assert a["meta"]["points"] == 420 and a["url"] == "https://github.com/x/bt"
    assert b["url"] == "https://news.ycombinator.com/item?id=102"   # Ask HN links to the discussion


# ---- markets & FRED ----------------------------------------------------------------
def history_for(closes):
    idx = pd.date_range(end="2026-10-21", periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 0}, index=idx)


INSTR = [{"ticker": "^GSPC", "name": "S&P 500", "kind": "index"},
         {"ticker": "^TNX", "name": "10-year Treasury yield", "kind": "rate"},
         {"ticker": "BAD", "name": "Broken", "kind": "index"}]


def fake_history(t):
    if t == "^GSPC":
        return history_for([5800, 5810, 5820, 5700.0])   # -2.06 %: notable
    if t == "^TNX":
        return history_for([4.10, 4.12, 4.13, 4.18])     # +5 bp: not notable
    raise ValueError("no data")


def test_gdelt_queries_reach_the_library_as_or_lists(profile):
    from gdeltdoc import Filters
    sent = []
    GdeltSource(profile.sources["gdelt"]["queries"], search=lambda q, ts, n: sent.append(q), pause=0).collect()
    qs = Filters(keyword=sent[0], timespan="1d", num_records=25, language="english").query_string
    assert qs.startswith('("quantitative trading" OR "quant fund" OR "hedge fund")')


def test_market_snapshot_and_moves():
    res = MarketSource(INSTR, history=fake_history).collect()
    rows = {r["ticker"]: r for r in res.extra["markets"]["rows"]}
    assert rows["^GSPC"]["change_pct"] == -2.06 and rows["^GSPC"]["closes"][-1] == 5700.0
    assert rows["^TNX"]["change_bp"] == 5.0
    assert list(res.items) == ["mkt:^GSPC:2026-10-21"]
    assert res.items["mkt:^GSPC:2026-10-21"]["title"] == "S&P 500 fell 2.1% on 2026-10-21"
    assert res.errors[0]["source"] == "Markets: Broken"


def test_rate_moves_are_measured_in_basis_points():
    res = MarketSource([INSTR[1]], history=lambda t: history_for([4.10, 4.25])).collect()
    assert res.items["mkt:^TNX:2026-10-21"]["title"] == "10-year Treasury yield rose 15 bp to 4.25% on 2026-10-21"


def test_fred_needs_a_key_then_reads_series(tmp_path, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    series = [{"id": "CPIAUCSL", "name": "CPI", "units": "index", "yoy": True}, {"id": "UNRATE", "name": "Unemployment", "units": "%"}]
    assert FredSource(series, api_key=None).collect().extra["macro"]["needs_key"] is True
    (tmp_path / ".env").write_text('FRED_API_KEY="abc123"\n')
    assert fred_key(tmp_path) == "abc123"

    def fetch(sid):
        idx = pd.date_range(end="2026-09-01", periods=13, freq="MS")
        vals = [300 + i for i in range(13)] if sid == "CPIAUCSL" else [4.0] * 12 + [4.1]
        return pd.Series(vals, index=idx)
    rows = {r["id"]: r for r in FredSource(series, api_key="abc123", fetch=fetch).collect().extra["macro"]["rows"]}
    assert rows["CPIAUCSL"]["yoy_pct"] == 4.0 and rows["UNRATE"]["latest"] == 4.1 and rows["UNRATE"]["previous"] == 4.0


# ---- ranking & clustering ---------------------------------------------------------------
def test_ranking_knows_its_sources(profile):
    r = Ranker(profile)
    pub = NOW.isoformat()
    fed = r.score({"title": "Federal Reserve issues FOMC statement", "abstract": "target range for the federal funds rate",
                   "source_type": "official", "source": "Federal Reserve press releases", "published_at": pub})
    hn = r.score({"title": "Show HN: vectorized backtester in JAX", "abstract": "", "source_type": "discussion",
                  "source": "Hacker News", "meta": {"points": 420}, "published_at": pub})
    move = r.score({"title": "S&P 500 fell 2.1%", "source_type": "market_move", "meta": {"change_pct": -2.1}, "published_at": pub})
    assert fed.breakdown["Q"] == 0.9 and fed.area == "markets_macro"
    assert "420 points on Hacker News" in hn.why
    assert move.area == "markets_macro" and move.breakdown["I"] > 0.6
    old_news = r.score({"title": "Fed holds rates", "source_type": "news", "published_at": (NOW - timedelta(days=2)).isoformat()})
    old_paper = r.score({"title": "Fed holds rates", "source_type": "academic_paper", "published_at": (NOW - timedelta(days=2)).isoformat()})
    assert old_news.breakdown["F"] < old_paper.breakdown["F"]   # news goes stale faster


def test_same_story_from_several_outlets_becomes_one_item():
    mk = lambda i, t, d, top=False: {"id": i, "title": t, "source_type": "news", "source": d,  # noqa: E731
                                     "published_at": "2026-10-21T10:00:00+00:00", "meta": {"domain": d, "top_outlet": top}}
    items = {x["id"]: x for x in [
        mk("a", "Fed holds interest rates steady as inflation cools", "smallblog.example"),
        mk("b", "Fed holds interest rates steady, inflation cools", "reuters.com", top=True),
        mk("c", "Fed holds interest rates steady as inflation cools further", "cnbc.com", top=True),
        mk("d", "Nvidia unveils new AI chip", "cnbc.com", top=True),
    ]}
    keep, merged = cluster_stories(items, recent=[])
    assert set(keep) == {"b", "d"}                   # Reuters copy leads the cluster
    assert sorted(merged["b"]) == ["cnbc.com", "smallblog.example"]


# ---- whole pipeline -----------------------------------------------------------------------
def test_full_briefing_mixes_papers_news_and_markets(full_service, db, settings, profile):
    out = full_service.run_briefing("manual")
    assert out["status"] == "partial"                      # broken feed + broken ticker reported, rest worked
    ids = db.latest_briefing()["item_ids"]
    types = {db.get_paper(i)["source_type"] for i in ids}
    assert {"academic_paper", "official", "news", "market_move"} <= types
    fed_news = [p for p in db.list_papers(kind="news", limit=100) if p["source_type"] == "news"]
    assert len(fed_news) == 1 and fed_news[0]["meta"]["coverage"] == ["cnbc.com"]

    with TestClient(create_app(settings, profile, full_service, start_scheduler=False)) as c:
        m = c.get("/api/markets").json()
        assert [r["ticker"] for r in m["markets"]["rows"]] == ["^GSPC", "^TNX"]
        assert m["macro"]["needs_key"] is True
        papers = c.get("/api/papers", params={"kind": "papers"}).json()
        assert papers and all(p["source"] == "arXiv" for p in papers)
        news = c.get("/api/papers", params={"kind": "news"}).json()
        assert news and all(p["source_type"] != "academic_paper" for p in news)
        hn = c.get("/api/papers/hn:7").json()
        assert hn["meta"]["points"] == 300 and hn["meta"]["discussion_url"].endswith("id=7")
