from butler.collector import ArxivCollector, clean, split_id
from fake_arxiv import CORPUS, default_route, fake_client


def test_split_id():
    assert split_id("http://arxiv.org/abs/2410.01234v2") == ("2410.01234", "v2")
    assert split_id("http://arxiv.org/abs/q-fin/0601001v1") == ("q-fin/0601001", "v1")
    assert split_id("http://arxiv.org/abs/2410.01234") == ("2410.01234", None)


def test_clean_strips_control_chars_and_whitespace():
    assert clean("  Deep\n\n  hedging\x07 ") == "Deep hedging"


def test_clean_decodes_latex_accents():
    # real arXiv metadata from the q-fin feed
    assert clean(r"infinite variation L\'evy jumps") == "infinite variation Lévy jumps"
    assert clean(r"\`Oscar Bur\'es") == "Òscar Burés"
    assert clean(r'Kassian K\"ock') == "Kassian Köck"
    assert clean(r"Jim\'{e}nez") == "Jiménez"
    assert clean(r"the $\sigma$-field") == r"the $\sigma$-field"   # real math is left alone


def test_collect_parses_with_real_arxiv_library_and_dedupes(profile):
    client, adapter = fake_client(default_route)
    res = ArxivCollector(profile.searches, client).collect()

    assert len(adapter.calls) == len(profile.searches)       # every configured search ran
    assert res.errors == []
    ids = set(res.papers)
    assert ids == {e["pid"] for e in CORPUS.values()}         # deduped across overlapping searches
    assert res.fetched > len(ids)                             # overlaps were fetched but merged

    lob = res.papers["2610.90002"]
    assert lob["title"] == "Transformer Models for Limit Order Book Forecasting"
    assert lob["version"] == "v1"
    assert lob["url"] == "https://arxiv.org/abs/2610.90002"
    assert lob["primary_category"] == "q-fin.TR"
    assert lob["comment"] == "Accepted at NeurIPS 2026"
    assert lob["content_access"] == "abstract_only"
    assert len(lob["found_by"]) >= 3                          # found by several searches
    assert lob["published_at"] != lob["retrieved_at"]         # publication ≠ retrieval time
    assert res.papers["2610.90003"]["journal_ref"].startswith("Quantitative Finance")


def test_one_failing_search_does_not_stop_the_others(profile):
    def route(q):
        if "large language model" in q:
            raise ConnectionError("simulated outage")
        return default_route(q)

    client, _ = fake_client(route)
    res = ArxivCollector(profile.searches, client).collect()
    assert len(res.errors) == 1 and "LLMs & agents" in res.errors[0]["source"]
    assert "2610.90001" in res.papers and "2610.90004" not in res.papers
