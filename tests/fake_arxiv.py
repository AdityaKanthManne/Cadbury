"""Serve arXiv-API-format Atom feeds to the real `arxiv` library, without network.

The papers here are SYNTHETIC test data (ids 2610.9xxxx) — never real articles.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

import requests
from requests.adapters import BaseAdapter


def entry(pid: str, title: str, abstract: str, cats: List[str], days_ago: float = 0.5,
          authors=("A. Researcher", "B. Scientist"), comment: str = "", journal_ref: str = "",
          version: int = 1) -> Dict:
    pub = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dict(pid=pid, title=title, abstract=abstract, cats=cats, published=pub,
                authors=list(authors), comment=comment, journal_ref=journal_ref, version=version)


def atom(entries: List[Dict]) -> str:
    def one(e):
        ts = e["published"].strftime("%Y-%m-%dT%H:%M:%SZ")
        cats = "".join(f'<category term="{c}" scheme="http://arxiv.org/schemas/atom"/>' for c in e["cats"])
        authors = "".join(f"<author><name>{escape(a)}</name></author>" for a in e["authors"])
        extra = ""
        if e["comment"]:
            extra += f"<arxiv:comment>{escape(e['comment'])}</arxiv:comment>"
        if e["journal_ref"]:
            extra += f"<arxiv:journal_ref>{escape(e['journal_ref'])}</arxiv:journal_ref>"
        vid = f"{e['pid']}v{e['version']}"
        return f"""
  <entry>
    <id>http://arxiv.org/abs/{vid}</id>
    <updated>{ts}</updated>
    <published>{ts}</published>
    <title>{escape(e['title'])}</title>
    <summary>{escape(e['abstract'])}</summary>
    {authors}
    {extra}
    <link href="http://arxiv.org/abs/{vid}" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/{vid}" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="{e['cats'][0]}" scheme="http://arxiv.org/schemas/atom"/>
    {cats}
  </entry>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query</title>
  <id>http://arxiv.org/api/test</id>
  <updated>2026-10-20T00:00:00-04:00</updated>
  <opensearch:totalResults>{len(entries)}</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>{len(entries)}</opensearch:itemsPerPage>
  {''.join(one(e) for e in entries)}
</feed>"""


class FakeArxivAdapter(BaseAdapter):
    """route(search_query) -> list of entries, or raises to simulate an outage."""

    def __init__(self, route: Callable[[str], List[Dict]]):
        super().__init__()
        self.route = route
        self.calls: List[str] = []

    def send(self, request, **kwargs):
        qs = parse_qs(urlparse(request.url).query)
        query = qs.get("search_query", [""])[0]
        start = int(qs.get("start", ["0"])[0])
        self.calls.append(query)
        entries = self.route(query) if start == 0 else []
        resp = requests.Response()
        resp.status_code = 200
        resp._content = atom(entries).encode()
        resp.headers["Content-Type"] = "application/atom+xml"
        resp.url = request.url
        resp.request = request
        return resp

    def close(self):
        pass


def fake_client(route: Callable[[str], List[Dict]]):
    import arxiv
    client = arxiv.Client(page_size=100, delay_seconds=0, num_retries=0)
    adapter = FakeArxivAdapter(route)
    client._session.mount("https://", adapter)
    client._session.mount("http://", adapter)
    return client, adapter


# -- a small synthetic corpus ---------------------------------------------------
CORPUS = {
    "hedging": entry(
        "2610.90001", "Deep Hedging with Reinforcement Learning under Rough Volatility",
        "We propose a reinforcement learning framework for deep hedging of options under rough "
        "volatility. On real data from S&P 500 options it outperforms delta hedging out-of-sample. "
        "Code is available at github.com/example/deephedge.",
        ["q-fin.CP", "cs.LG"], days_ago=0.3),
    "lob": entry(
        "2610.90002", "Transformer Models for Limit Order Book Forecasting",
        "We study transformer architectures for forecasting mid-price moves from limit order book "
        "data and market microstructure features, with a large-scale empirical benchmark.",
        ["q-fin.TR", "cs.LG"], days_ago=1.2, comment="Accepted at NeurIPS 2026"),
    "execution": entry(
        "2610.90003", "Optimal Execution with Stochastic Liquidity",
        "We derive closed-form optimal execution strategies when liquidity is stochastic, "
        "extending Almgren-Chriss.", ["q-fin.TR"], days_ago=2.0,
        journal_ref="Quantitative Finance 26 (2026)"),
    "llm_agents": entry(
        "2610.90004", "Planning Agents Built on Large Language Models",
        "We introduce an agent framework in which large language models plan multi-step tool use "
        "and evaluate it on a new benchmark.", ["cs.AI"], days_ago=0.8),
    "macro": entry(
        "2610.90005", "Monetary Policy Shocks and the Treasury Yield Curve",
        "We estimate how Federal Reserve monetary policy surprises propagate through the Treasury "
        "yield curve using high-frequency data.", ["q-fin.GN", "econ.GN"], days_ago=1.0),
    "offtopic": entry(
        "2610.90006", "Segmenting Cell Nuclei in Microscopy Images",
        "A convolutional approach to segmentation of nuclei in fluorescence microscopy.",
        ["cs.CV", "cs.LG"], days_ago=0.1),
    "stale": entry(
        "2610.90007", "A Survey of Portfolio Optimization Methods",
        "We survey portfolio optimization from mean-variance to risk parity.",
        ["q-fin.PM"], days_ago=20),
}


def default_route(query: str) -> List[Dict]:
    """Roughly mimic what each configured search would return; some overlap on purpose."""
    c = CORPUS
    if "q-fin.PM" in query:  # all q-fin
        return [c["hedging"], c["lob"], c["execution"], c["macro"], c["stale"]]
    if "finance" in query:  # ML x Finance
        return [c["hedging"], c["lob"]]
    if "market microstructure" in query:
        return [c["lob"], c["execution"]]
    if "time series" in query:
        return [c["lob"], c["offtopic"]]
    if "large language model" in query:
        return [c["llm_agents"]]
    return []
