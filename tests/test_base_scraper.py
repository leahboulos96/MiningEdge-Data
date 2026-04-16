"""Tests for BaseScraper normalization, dedup, persistence and failure
isolation. A fake scraper is used so no HTTP is involved."""

import pytest
from scrapers.base_scraper import BaseScraper


class FakeScraper(BaseScraper):
    name = "fake_source"
    source_group = "news"
    record_type = "news"

    def __init__(self, raw_records=None, boom=False):
        super().__init__()
        self._raw = raw_records or []
        self._boom = boom

    def run(self):
        if self._boom:
            raise RuntimeError("simulated scraper crash")
        return self._raw


def _raw(external_id, title="Sample mining headline"):
    return {
        "tender_id_external": external_id,
        "title": title,
        "description_raw": "mining description",
        "issuing_entity_name": "BHP",
        "url": f"https://example.com/{external_id}",
    }


def test_execute_normalizes_and_inserts(fresh_db):
    db = fresh_db
    s = FakeScraper(raw_records=[_raw("A"), _raw("B")])
    s.execute()
    rows = db.list_records()
    assert len(rows) == 2
    titles = sorted(r["title"] for r in rows)
    assert titles == ["Sample mining headline", "Sample mining headline"]
    assert rows[0]["source"] == "fake_source"
    assert rows[0]["source_group"] == "news"


def test_execute_dedups_within_same_run(fresh_db):
    db = fresh_db
    s = FakeScraper(raw_records=[_raw("A"), _raw("A")])
    s.execute()
    assert db.count_records() == 1
    assert s.stats["new"] == 1
    assert s.stats["skipped"] == 1


def test_execute_second_run_skips_existing(fresh_db):
    db = fresh_db
    FakeScraper(raw_records=[_raw("A")]).execute()
    # Run again with new + duplicate
    s2 = FakeScraper(raw_records=[_raw("A"), _raw("B")])
    s2.execute()
    assert db.count_records() == 2
    assert s2.stats["new"] == 1


def test_execute_respects_permanent_discard(fresh_db):
    db = fresh_db
    FakeScraper(raw_records=[_raw("X")]).execute()
    rec = db.list_records(status="pending")[0]
    db.update_record_status(rec["id"], "discarded")

    # Scrape again - should not be re-inserted
    s = FakeScraper(raw_records=[_raw("X")])
    s.execute()
    assert db.count_records(status="pending") == 0


def test_execute_does_not_raise_on_crash(fresh_db):
    """A failing scraper must never crash the caller - it records the error."""
    db = fresh_db
    run_id = db.start_scraper_run("fake_source", triggered_by="test")
    s = FakeScraper(boom=True)
    # MUST NOT raise
    s.execute(run_id=run_id)
    assert s.stats["errors"] >= 1
    row = db.recent_scraper_runs(limit=1)[0]
    assert row["status"] == "error"
    assert "crash" in (row["error_message"] or "").lower()


def test_dedup_hash_is_stable_for_same_inputs(fresh_db):
    """Scraping the same logical record twice - even with different wrapper
    dict ordering - yields the same dedup hash and therefore one row."""
    db = fresh_db
    FakeScraper(raw_records=[_raw("Z", title="Title one")]).execute()
    FakeScraper(raw_records=[_raw("Z", title="Title one altered later")]).execute()
    # Same external_id -> same dedup_hash -> second insert rejected
    assert db.count_records() == 1
