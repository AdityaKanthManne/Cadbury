import json
import sqlite3

from fastapi.testclient import TestClient

from butler.api import create_app
from butler.db import MIGRATIONS, Database
from butler.sections import SECTION_KEYS, section_of


def test_section_mapping():
    assert section_of({"source_type": "academic_paper"}, "quant_finance") == "research"
    assert section_of({"source_type": "market_move"}) == "market"
    assert section_of({"source_type": "official"}) == "market"            # Fed releases
    assert section_of({"source_type": "lab_blog"}) == "tech"
    assert section_of({"source_type": "research_blog"}) == "tech"         # Jane Street engineering blog
    assert section_of({"source_type": "discussion"}) == "tech"            # Hacker News
    assert section_of({"source_type": "news"}, "markets_macro") == "market"
    assert section_of({"source_type": "news"}, "ai_ml") == "tech"
    assert section_of({"source_type": "news"}, "quant_finance") == "news"
    assert section_of({"source_type": "news"}, None) == "news"
    assert SECTION_KEYS == ["market", "research", "news", "tech"]


def test_upgrading_a_database_from_the_first_release_keeps_papers(tmp_path):
    """Your Mac's butler.db was created by the papers-only build (schema v1)."""
    path = tmp_path / "butler.db"
    con = sqlite3.connect(path)
    con.executescript(MIGRATIONS[0])
    con.execute("PRAGMA user_version = 1")
    con.execute(
        "INSERT INTO papers (id, title, authors, retrieved_at, url, source, source_type, score, area) "
        "VALUES ('2610.00001', 'An old paper', ?, '2026-10-20T12:00:00+00:00', 'https://arxiv.org/abs/2610.00001', "
        "'arXiv', 'academic_paper', 70, 'quant_finance')", (json.dumps(["A. Author"]),))
    con.execute("INSERT INTO bookmarks VALUES ('2610.00001', '2026-10-20T12:00:00+00:00')")
    con.commit()
    con.close()

    db = Database(path)
    assert db._conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    p = db.get_paper("2610.00001")
    assert p["title"] == "An old paper" and p["section"] == "research" and p["bookmarked"]
    assert db.section_counts() == {"research": 1}


def test_full_pipeline_fills_all_four_sections(full_service, db, settings, profile):
    full_service.run_briefing("manual")
    counts = db.section_counts()
    assert set(counts) == {"market", "research", "news", "tech"} or set(counts) >= {"market", "research", "tech"}
    with TestClient(create_app(settings, profile, full_service, start_scheduler=False)) as c:
        prof = c.get("/api/profile").json()
        assert [s["label"] for s in prof["sections"]] == ["Market", "Research", "News", "Tech developments"]
        for key in ("market", "research", "tech"):
            items = c.get("/api/papers", params={"section": key}).json()
            assert items and all(i["section"] == key for i in items), key
        market = {i["source_type"] for i in c.get("/api/papers", params={"section": "market"}).json()}
        assert {"market_move", "official"} <= market
        assert c.get("/api/status").json()["section_counts"] == counts
        assert c.get("/api/papers", params={"section": "sports"}).status_code == 422
