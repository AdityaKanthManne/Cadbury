from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fake_arxiv import default_route

ET = ZoneInfo("America/New_York")


def test_full_briefing_pipeline(make_service, db):
    svc = make_service()
    out = svc.run_briefing("manual")
    assert out["status"] == "ok"
    assert out["new_papers"] == 7

    b = db.latest_briefing()
    ids = b["item_ids"]
    assert "2610.90006" not in ids            # off-topic microscopy paper filtered out
    assert ids[0] == "2610.90001"             # deep hedging + RL + code ranks first
    scores = [db.get_paper(i)["score"] for i in ids]
    assert scores == sorted(scores, reverse=True)

    # second run: nothing new, nothing duplicated
    out2 = svc.run_briefing("scheduled")
    assert out2["new_papers"] == 0 and db.count_papers() == 7


def test_offline_briefing_fails_but_keeps_previous_data(make_service, db):
    make_service().run_briefing("manual")
    good = db.latest_briefing()

    def offline(_q):
        raise ConnectionError("no network")

    out = make_service(offline).run_briefing("scheduled")
    assert out["status"] == "failed" and len(out["errors"]) == 6
    assert db.latest_briefing()["id"] == good["id"]    # UI still shows the last good briefing
    assert db.count_papers() == 7


def test_partial_failure(make_service):
    def route(q):
        if "cs.CE" in q:
            raise TimeoutError("slow")
        return default_route(q)
    assert make_service(route).run_briefing("manual")["status"] == "partial"


def test_not_relevant_feedback_excluded_from_next_briefing(make_service, db):
    svc = make_service()
    svc.run_briefing("manual")
    db.add_feedback("2610.90001", "not_relevant")
    svc.run_briefing("manual")
    assert "2610.90001" not in db.latest_briefing()["item_ids"]


def test_schedule_slots_are_8am_and_8pm_eastern(make_service):
    svc = make_service()
    t = lambda *a: datetime(*a, tzinfo=ET).astimezone(timezone.utc)
    assert svc.last_slot(t(2026, 10, 20, 7, 59)).hour == 20          # yesterday 8 PM
    assert svc.last_slot(t(2026, 10, 20, 8, 0)) == datetime(2026, 10, 20, 8, tzinfo=ET)
    assert svc.last_slot(t(2026, 10, 20, 23, 0)) == datetime(2026, 10, 20, 20, tzinfo=ET)
    nxt = svc.next_slots(2, t(2026, 10, 20, 19, 59))
    assert [s.hour for s in nxt] == [20, 8]
    # DST: 8 AM Eastern stays 8 AM local after clocks change (Nov 1 2026)
    assert svc.next_slots(1, t(2026, 11, 1, 7, 0))[0].hour == 8


def test_catch_up_after_sleeping_through_8am(make_service, db):
    svc = make_service()
    assert svc.needs_catch_up()                  # never ran
    svc.run_briefing("startup")
    assert not svc.needs_catch_up()
    later = datetime.now(timezone.utc).replace(microsecond=0)
    from datetime import timedelta
    assert svc.needs_catch_up(later + timedelta(hours=13))   # a slot has passed since


def test_concurrent_runs_are_skipped(make_service):
    svc = make_service()
    svc._run_lock.acquire()
    try:
        assert svc.run_briefing("manual") is None
        assert svc.run_in_background("manual") is False
    finally:
        svc._run_lock.release()
