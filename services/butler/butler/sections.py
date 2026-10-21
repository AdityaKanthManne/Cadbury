"""The four sections the dashboard is organised into.

Interest areas (configs/user_profile.yaml) decide how relevant something is;
sections decide where it is shown:

    market    price moves, central-bank releases, market & macro news
    research  arXiv papers
    news      industry news: quant firms, funds, careers, quant x AI stories
    tech      AI-lab and engineering blogs, Hacker News, AI and infrastructure news
"""

from __future__ import annotations

from typing import Dict, Optional

SECTIONS = [
    ("market", "Market"),
    ("research", "Research"),
    ("news", "News"),
    ("tech", "Tech developments"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]

_BY_SOURCE = {
    "market_move": "market",
    "official": "market",
    "academic_paper": "research",
    "lab_blog": "tech",
    "research_blog": "tech",
    "discussion": "tech",
}
_NEWS_BY_AREA = {
    "markets_macro": "market",
    "ai_ml": "tech",
    "infra": "tech",
}


def section_of(item: Dict, area: Optional[str] = None) -> str:
    stype = item.get("source_type") or "academic_paper"
    if stype in _BY_SOURCE:
        return _BY_SOURCE[stype]
    return _NEWS_BY_AREA.get(area or item.get("area") or "", "news")
