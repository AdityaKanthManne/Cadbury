from datetime import datetime, timedelta, timezone

from butler.ranking import WEIGHTS, Ranker, select_briefing

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def paper(title, abstract, cats=("q-fin.TR",), days=0.5, **kw):
    return {"title": title, "abstract": abstract, "categories": list(cats),
            "published_at": (NOW - timedelta(days=days)).isoformat(), **kw}


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1) < 1e-9


def test_relevant_beats_irrelevant(profile):
    r = Ranker(profile, now=NOW)
    good = r.score(paper("Deep Hedging with Reinforcement Learning",
                         "We propose a reinforcement learning approach to deep hedging of options. "
                         "Code is available on github.com.", ("q-fin.CP", "cs.LG")))
    bad = r.score(paper("Segmenting Cell Nuclei in Microscopy Images",
                        "A convolutional approach to segmentation.", ("cs.CV",), days=0.01))
    assert good.score > 60
    assert bad.score < 30 and bad.breakdown["filtered"]
    assert good.area == "quant_ai"           # quant + ML lands in the intersection
    assert "deep hedging" in good.why.lower() and "Code released" in good.why


def test_freshness_decays_but_cannot_rescue_off_topic(profile):
    r = Ranker(profile, now=NOW)
    base = ("Optimal Execution with Limit Order Book Signals", "We study optimal execution.")
    fresh, old = r.score(paper(*base, days=0)), r.score(paper(*base, days=12))
    assert fresh.breakdown["F"] > 0.95 and old.breakdown["F"] < 0.1
    assert fresh.score > old.score
    off = r.score(paper("A Recipe Recommender", "Food.", ("cs.IR",), days=0))
    assert off.score < old.score


def test_novelty_penalises_near_duplicates(profile):
    r = Ranker(profile, now=NOW)
    p = paper("Transformer Models for Limit Order Book Forecasting", "limit order book")
    assert r.score(p).breakdown["N"] == 1.0
    dup = r.score(p, ["Transformer Models for Limit Order Book Forecasting Revisited"])
    assert dup.breakdown["N"] < 0.5 and "already seen" in dup.why


def test_quality_uses_journal_ref_and_venue(profile):
    r = Ranker(profile, now=NOW)
    plain = r.score(paper("Market making", "market making"))
    journal = r.score(paper("Market making", "market making", journal_ref="Math. Finance 2026"))
    venue = r.score(paper("Market making", "market making", comment="Accepted at ICML 2026"))
    assert plain.breakdown["Q"] < venue.breakdown["Q"] < journal.breakdown["Q"]


def test_keywords_match_whole_words_only(profile):
    r = Ranker(profile, now=NOW)
    s = r.score(paper("Palpha and Alphabet soup", "Nothing here.", ("cs.CL",)))
    assert "quant_finance" not in s.matched   # 'alpha' must not match inside 'Palpha'/'Alphabet'


def test_matching_tolerates_hyphens_and_plurals(profile):
    r = Ranker(profile, now=NOW)
    s = r.score(paper("Reinforcement-learning trading agents",
                      "We forecast limit-order book supply with an LLM agent.", ("q-fin.TR",)))
    assert "reinforcement learning" in s.matched["ai_ml"]
    assert "limit order book" in s.matched["quant_finance"]
    assert "AI agent" not in s.matched["ai_ml"]       # 'LLM agent' is not 'AI agent'
    assert "LLM" in s.matched["ai_ml"]


def test_briefing_diversification_caps_each_area():
    papers = [{"id": str(i), "score": 90 - i, "area": "quant_finance", "breakdown": {}} for i in range(8)]
    papers += [{"id": "ml", "score": 50, "area": "ai_ml", "breakdown": {}},
               {"id": "low", "score": 10, "area": "infra", "breakdown": {}},
               {"id": "filt", "score": 80, "area": "careers", "breakdown": {"filtered": True}}]
    chosen = select_briefing(papers, size=10, max_per_area=4)
    ids = [p["id"] for p in chosen]
    assert ids == ["0", "1", "2", "3", "ml"]
