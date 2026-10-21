"""Baseline relevance ranking.

S = 0.30 R + 0.20 Q + 0.15 N + 0.15 I + 0.10 F + 0.10 P   (each signal in [0, 1])

These are the heuristic starting weights from the spec — not a fitted or
"optimal" model. Every score carries a per-signal breakdown and a plain-English
reason so you can see why something was recommended.

R  Relevance     keyword/phrase match against the interest profile (area weights applied).
                 Phase 3 will swap this for local sentence-transformer embeddings.
Q  Source quality arXiv preprint = 0.6; journal ref or accepted-at-venue comment raises it.
N  Novelty       1 − max title similarity to papers seen in the last 30 days.
I  Impact        evidence terms: benchmarks, real data, outperforms, large-scale, datasets.
F  Freshness     exponential decay on *publication* date, half-life 3 days.
P  Learning value code released / reproducible / implementable method.

Guards: items with near-zero relevance are halved (stage-1 filter) so freshness
or quality alone can't push an off-topic paper into the briefing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple

from .config import Profile

WEIGHTS = {"R": 0.30, "Q": 0.20, "N": 0.15, "I": 0.15, "F": 0.10, "P": 0.10}
SIGNAL_NAMES = {
    "R": "Relevance", "Q": "Source quality", "N": "Novelty",
    "I": "Impact", "F": "Freshness", "P": "Learning value",
}
FRESH_HALF_LIFE_DAYS = 3.0
# how fast each kind of item goes stale (days for freshness to halve)
HALF_LIFE = {"academic_paper": 3.0, "official": 2.0, "research_blog": 5.0, "lab_blog": 4.0,
             "news": 1.0, "discussion": 1.0, "market_move": 0.75}
SOURCE_QUALITY = {"official": 0.9, "research_blog": 0.8, "lab_blog": 0.75, "market_move": 0.85}
LOW_RELEVANCE = 0.15

IMPACT_TERMS = [
    "state of the art", "outperform", "benchmark",
    "real-world", "real data", "empirical", "large-scale", "high-frequency", "dataset",
    "out-of-sample", "live trading", "S&P 500", "significantly",
]
VENUE_TERMS = [
    "accepted", "neurips", "icml", "iclr", "kdd", "aaai", "ijcai", "acl", "emnlp",
    "quantitative finance", "mathematical finance", "journal of", "review of financial studies",
]
CODE_TERMS = ["github.com", "code is available", "code available", "open-source", "open source",
              "we release", "publicly available", "reproducib"]
METHOD_TERMS = ["we propose", "framework", "novel", "algorithm", "survey", "tutorial", "we introduce"]
QFIN_PREFIX = "q-fin."

_STOP = set("a an the of for and or in on with to by from via using under towards toward is are we our".split())
_TOKEN = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=4096)
def _phrase_re(phrase: str) -> re.Pattern:
    """Whole-word, case-insensitive. Spaces and hyphens are interchangeable
    ("limit order" ~ "limit-order"), and a trailing plural "s" is optional."""
    words = [re.escape(w) for w in re.split(r"[\s\-]+", phrase.strip()) if w]
    body = r"[\s\-]+".join(words)
    if phrase[-1:].isalpha() and not phrase.endswith("s"):
        body += "s?"
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _hits(text: str, phrases: Iterable[str]) -> List[str]:
    found = [p for p in dict.fromkeys(phrases) if _phrase_re(p).search(text)]
    # "limit order" adds nothing when "limit order book" also matched
    norm = lambda x: re.sub(r"[\s\-]+", " ", x.lower())  # noqa: E731
    return [p for p in found if not any(q != p and norm(p) in norm(q) for q in found)]


def _sat(x: float, k: float) -> float:
    """Saturating 0..1 transform."""
    return 1.0 - math.exp(-x / k)


def title_tokens(title: str) -> frozenset:
    return frozenset(t for t in _TOKEN.findall(title.lower()) if t not in _STOP and len(t) > 2)


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass
class Scored:
    area: str
    score: float           # 0..100
    breakdown: Dict[str, float]
    why: str
    matched: Dict[str, List[str]]


class Ranker:
    def __init__(self, profile: Profile, now: Optional[datetime] = None):
        self.profile = profile
        self.now = now
        wmax = max((a.weight for a in profile.areas.values()), default=1) or 1
        # area weight nudges, never dominates: 0.6 .. 1.0
        self.area_mult = {k: 0.6 + 0.4 * (a.weight / wmax) for k, a in profile.areas.items()}

    # -- signals --------------------------------------------------------
    def relevance(self, paper: Dict) -> Tuple[float, str, Dict[str, List[str]]]:
        if paper.get("source_type") == "market_move":
            return 0.8, "markets_macro" if "markets_macro" in self.profile.areas else self._fallback_area([]), {}
        title, abstract = paper.get("title", ""), paper.get("abstract", "")
        matched: Dict[str, List[str]] = {}
        area_scores: Dict[str, float] = {}
        for key, area in self.profile.areas.items():
            in_title = _hits(title, area.keywords)
            in_abs = _hits(abstract, area.keywords)
            kws = list(dict.fromkeys(in_title + in_abs))
            if not kws:
                continue
            matched[key] = kws
            raw = 2.0 * len(in_title) + 1.0 * len(in_abs)
            area_scores[key] = _sat(raw, 2.5) * self.area_mult[key]

        cats = paper.get("categories") or []
        if not area_scores:
            stype = paper.get("source_type", "academic_paper")
            if stype == "official":  # central-bank releases are on-topic by definition
                return 0.45, "markets_macro" if "markets_macro" in self.profile.areas else self._fallback_area(cats), matched
            if stype == "research_blog":
                return 0.35, "infra" if "infra" in self.profile.areas else self._fallback_area(cats), matched
            prior = 0.35 if any(c.startswith(QFIN_PREFIX) for c in cats) else 0.05
            area = "quant_finance" if prior > 0.1 else self._fallback_area(cats)
            return prior, area, matched

        ranked = sorted(area_scores.items(), key=lambda kv: kv[1], reverse=True)
        primary, best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        # a paper that is both quant and AI belongs in "Quant + AI"
        if "quant_finance" in area_scores and "ai_ml" in area_scores and "quant_ai" in self.profile.areas:
            primary = "quant_ai"
        r = min(1.0, best + 0.25 * second)
        if any(c.startswith(QFIN_PREFIX) for c in cats):
            r = min(1.0, r + 0.1)
        return r, primary, matched

    def _fallback_area(self, cats: List[str]) -> str:
        if any(c.startswith(("cs.", "stat.")) for c in cats) and "ai_ml" in self.profile.areas:
            return "ai_ml"
        return next(iter(self.profile.areas), "other")

    @staticmethod
    def quality(paper: Dict) -> Tuple[float, Optional[str]]:
        stype, meta = paper.get("source_type", "academic_paper"), paper.get("meta") or {}
        if stype in SOURCE_QUALITY:
            return SOURCE_QUALITY[stype], None
        if stype == "news":
            coverage = len(meta.get("coverage") or [])
            q = (0.7 if meta.get("top_outlet") else 0.5) + min(0.15, 0.05 * coverage)
            return q, f"covered by {coverage + 1} outlets" if coverage else None
        if stype == "discussion":
            pts = meta.get("points") or 0
            return min(0.75, 0.45 + pts / 1500), f"{pts} points on Hacker News"
        if paper.get("journal_ref"):
            return 0.8, "appeared in a journal"
        comment = (paper.get("comment") or "")
        if _hits(comment, VENUE_TERMS):
            return 0.75, "accepted at a venue"
        return 0.6, None

    @staticmethod
    def novelty(paper: Dict, recent_titles: Iterable[str]) -> float:
        mine = title_tokens(paper.get("title", ""))
        best = max((jaccard(mine, title_tokens(t)) for t in recent_titles), default=0.0)
        return 1.0 - best

    @staticmethod
    def impact(paper: Dict) -> Tuple[float, List[str]]:
        stype, meta = paper.get("source_type"), paper.get("meta") or {}
        if stype == "market_move":
            size = abs(meta.get("change_pct") or 0)
            return min(1.0, 0.5 + size / 10), []
        hits = _hits(paper.get("title", "") + " " + paper.get("abstract", "") + " " + (paper.get("comment") or ""), IMPACT_TERMS)
        base = _sat(len(hits), 2.0)
        if stype == "discussion":
            base = max(base, _sat((meta.get("points") or 0) / 100, 3.0))
        if stype == "news":
            base = max(base, _sat(len(meta.get("coverage") or []), 2.0))
        return base, hits

    def freshness(self, paper: Dict) -> Tuple[float, Optional[float]]:
        pub = paper.get("published_at")
        if not pub:
            return 0.3, None
        now = self.now or datetime.now(timezone.utc)
        age = max(0.0, (now - datetime.fromisoformat(pub)).total_seconds() / 86400)
        half_life = HALF_LIFE.get(paper.get("source_type", "academic_paper"), FRESH_HALF_LIFE_DAYS)
        return 0.5 ** (age / half_life), age

    @staticmethod
    def learning_value(paper: Dict) -> Tuple[float, bool]:
        text = paper.get("abstract", "") + " " + (paper.get("comment") or "")
        code = bool(_hits(text, CODE_TERMS))
        method = len(_hits(text, METHOD_TERMS))
        return min(1.0, (0.55 if code else 0.0) + 0.15 * method + 0.15), code

    # -- combined -------------------------------------------------------
    def score(self, paper: Dict, recent_titles: Iterable[str] = ()) -> Scored:
        self._stype, self._source = paper.get("source_type", "academic_paper"), paper.get("source") or ""
        R, area, matched = self.relevance(paper)
        Q, q_note = self.quality(paper)
        N = self.novelty(paper, recent_titles)
        I, impact_hits = self.impact(paper)
        F, age = self.freshness(paper)
        P, has_code = self.learning_value(paper)
        b = {"R": R, "Q": Q, "N": N, "I": I, "F": F, "P": P}
        s = sum(WEIGHTS[k] * v for k, v in b.items())
        filtered = R < LOW_RELEVANCE
        if filtered:
            s *= 0.5
        b = {k: round(v, 3) for k, v in b.items()}
        b["filtered"] = filtered
        return Scored(area=area, score=round(100 * s, 1), breakdown=b,
                      why=self._why(area, matched, q_note, impact_hits, has_code, age, N, filtered),
                      matched=matched)

    def _why(self, area, matched, q_note, impact_hits, has_code, age, novelty, filtered) -> str:
        parts = []
        if matched:
            labels = []
            # lead with the paper's primary area, then the areas with most matches
            order = sorted(matched.items(), key=lambda kv: (kv[0] != area, -len(kv[1])))
            for key, kws in order[:2]:
                label = self.profile.areas[key].label
                labels.append(f"{label}: {', '.join(kws[:3])}")
            parts.append("Matches " + "; ".join(labels))
        elif filtered:
            parts.append("Weak match to your interests")
        elif self._stype == "market_move":
            parts.append("A notable market move today")
        elif self._stype == "official":
            parts.append("Official release from the Federal Reserve" if "Federal Reserve" in self._source else f"Official release ({self._source})")
        elif self._stype in ("research_blog", "lab_blog"):
            parts.append(f"New post from {self._source}")
        else:
            parts.append("Quant-finance category on arXiv")
        if has_code:
            parts.append("Code released")
        if impact_hits:
            parts.append("Evidence: " + ", ".join(impact_hits[:2]))
        if q_note:
            parts.append(q_note[0].upper() + q_note[1:])
        if novelty < 0.5:
            parts.append("Similar to something you've already seen")
        return ". ".join(parts) + "."


KIND_GROUP = {"academic_paper": "papers", "discussion": "discussion"}  # everything else counts as "news"


def select_briefing(papers: List[Dict], size: int, max_per_area: int, min_score: float = 35.0,
                    max_per_kind: Optional[Dict[str, int]] = None) -> List[Dict]:
    """Top-scored items with coverage diversification: no area, and no kind of source, dominates."""
    caps = {"papers": 6, "news": 6, "discussion": 2, **(max_per_kind or {})}
    chosen, per_area, per_kind = [], {}, {}
    for p in sorted(papers, key=lambda p: p.get("score") or 0, reverse=True):
        if (p.get("score") or 0) < min_score or (p.get("breakdown") or {}).get("filtered"):
            continue
        a = p.get("area") or "other"
        k = KIND_GROUP.get(p.get("source_type") or "academic_paper", "news")
        if per_area.get(a, 0) >= max_per_area or per_kind.get(k, 0) >= caps.get(k, size):
            continue
        chosen.append(p)
        per_area[a] = per_area.get(a, 0) + 1
        per_kind[k] = per_kind.get(k, 0) + 1
        if len(chosen) >= size:
            break
    return chosen
