"""Tests for the scheduler's failure isolation and report writing."""

import pytest
import scheduler as sched_mod
import registry
from scrapers.base_scraper import BaseScraper


class OKScraper(BaseScraper):
    name = "test_ok"
    source_group = "news"
    record_type = "news"
    def run(self):
        return [{"tender_id_external": "ok-1", "title": "ok record",
                 "url": "http://x"}]


class BoomScraper(BaseScraper):
    name = "test_boom"
    source_group = "news"
    record_type = "news"
    def run(self):
        raise RuntimeError("simulated failure")


@pytest.fixture
def patched_registry(monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "test_ok",
                        ("OK Scraper", OKScraper, "news"))
    monkeypatch.setitem(registry.REGISTRY, "test_boom",
                        ("Boom Scraper", BoomScraper, "news"))


def test_run_single_scraper_ok(fresh_db, patched_registry):
    db = fresh_db
    r = sched_mod.run_single_scraper("test_ok", triggered_by="unit")
    assert r["status"] == "ok"
    assert r["new"] == 1
    assert db.count_records() == 1


def test_run_single_scraper_error_is_isolated(fresh_db, patched_registry):
    db = fresh_db
    r = sched_mod.run_single_scraper("test_boom", triggered_by="unit")
    assert r["status"] == "error"
    # The run was recorded
    runs = db.recent_scraper_runs(limit=5, scraper="test_boom")
    assert runs and runs[0]["status"] == "error"


def test_run_schedule_partial_failure_report(fresh_db, patched_registry):
    """A schedule containing a good scraper and a failing one finishes with
    status='partial' and records BOTH sub-runs."""
    db = fresh_db
    sid = db.create_schedule(
        "mixed", ["test_ok", "test_boom"],
        {"minute": "0", "hour": "0"}, "")
    sched_mod.run_schedule(sid)
    runs = db.recent_schedule_runs(limit=1)
    assert len(runs) == 1
    r = runs[0]
    assert r["status"] == "partial"
    assert r["scrapers_ok"] == 1
    assert r["scrapers_failed"] == 1
    assert r["total_new"] == 1
    detail = db.get_schedule_run(r["id"])
    assert len(detail["scraper_runs"]) == 2


def test_run_schedule_all_ok(fresh_db, patched_registry):
    db = fresh_db
    sid = db.create_schedule("good", ["test_ok"],
                             {"minute": "0", "hour": "0"}, "")
    sched_mod.run_schedule(sid)
    assert db.recent_schedule_runs(limit=1)[0]["status"] == "ok"


def test_run_schedule_all_fail(fresh_db, patched_registry):
    db = fresh_db
    sid = db.create_schedule("bad", ["test_boom"],
                             {"minute": "0", "hour": "0"}, "")
    sched_mod.run_schedule(sid)
    assert db.recent_schedule_runs(limit=1)[0]["status"] == "error"


def test_run_schedule_expands_group(fresh_db, patched_registry, monkeypatch):
    """Targets with 'group:<name>' must resolve to all keys in that group."""
    db = fresh_db
    # Override registry.groups so only our two fakes are in 'news'
    monkeypatch.setattr(registry, "groups",
                        lambda: {"news": ["test_ok", "test_boom"]})
    sid = db.create_schedule("grp", ["group:news"],
                             {"minute": "0", "hour": "0"}, "")
    sched_mod.run_schedule(sid)
    detail = db.get_schedule_run(db.recent_schedule_runs(limit=1)[0]["id"])
    ran = {r["scraper"] for r in detail["scraper_runs"]}
    assert ran == {"test_ok", "test_boom"}
