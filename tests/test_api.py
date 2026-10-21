import time

import pytest
from fastapi.testclient import TestClient

from butler.api import create_app


@pytest.fixture
def client(make_service, settings, profile):
    svc = make_service()
    app = create_app(settings, profile, svc, start_scheduler=False)
    with TestClient(app) as c:
        c.svc = svc
        yield c


def wait_idle(svc, timeout=10):
    t0 = time.time()
    while svc._run_lock.locked() and time.time() - t0 < timeout:
        time.sleep(0.05)


def test_health_and_empty_state(client):
    assert client.get("/api/health").json()["ok"] is True
    latest = client.get("/api/briefings/latest").json()
    assert latest["briefing"] is None and latest["items"] == []
    st = client.get("/api/status").json()
    assert st["schedule"] == ["08:00", "20:00"] and st["timezone"] == "America/New_York"
    assert len(st["next_runs"]) == 2


def test_run_then_read_briefing(client):
    r = client.post("/api/briefings/run")
    assert r.status_code == 202 and r.json()["started"] is True
    wait_idle(client.svc)
    data = client.get("/api/briefings/latest").json()
    assert data["briefing"]["status"] == "ok"
    first = data["items"][0]
    assert first["id"] == "2610.90001"
    assert set(first["breakdown"]) >= {"R", "Q", "N", "I", "F", "P"}
    assert first["why"] and first["url"].startswith("https://arxiv.org/abs/")
    assert data["greeting"].endswith("Aditya.")
    assert first["id"] in data["alerts"] or first["score"] < 80


def test_filters_feedback_bookmarks(client):
    client.svc.run_briefing("manual")
    qf = client.get("/api/papers", params={"area": "quant_finance"}).json()
    assert qf and all(p["area"] == "quant_finance" for p in qf)
    assert [p["id"] for p in client.get("/api/papers", params={"q": "order book"}).json()] == ["2610.90002"]
    by_date = client.get("/api/papers", params={"sort": "date"}).json()
    assert by_date[0]["published_at"] >= by_date[-1]["published_at"]

    assert client.post("/api/papers/2610.90002/bookmark", json={"on": True}).json()["bookmarked"]
    assert [p["id"] for p in client.get("/api/papers", params={"bookmarked": True}).json()] == ["2610.90002"]
    assert client.post("/api/papers/2610.90002/feedback", json={"kind": "relevant"}).status_code == 200
    assert client.get("/api/papers/2610.90002").json()["feedback"] == "relevant"

    assert client.post("/api/papers/2610.90002/feedback", json={"kind": "hack"}).status_code == 422
    assert client.post("/api/papers/nope/bookmark", json={"on": True}).status_code == 404
    client.post("/api/personal-data/reset")
    assert client.get("/api/papers", params={"bookmarked": True}).json() == []


def test_cors_only_allows_the_desktop_app(client):
    ok = client.get("/api/health", headers={"Origin": "tauri://localhost"})
    assert ok.headers.get("access-control-allow-origin") == "tauri://localhost"
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
