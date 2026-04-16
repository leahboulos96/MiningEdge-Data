"""Tests for the unified DB layer: insert, dedup, permanent discard, status
transitions, schedule CRUD, scraper_runs, schedule_runs, settings, api_keys."""

import pytest


def _rec(**kw):
    base = {
        "source": "news_afr", "source_group": "news", "record_type": "news",
        "external_id": "ext-1", "title": "Mining headline",
        "description": "BHP lithium project",
        "dedup_hash": "hash-1",
    }
    base.update(kw)
    return base


def test_insert_and_duplicate(fresh_db):
    db = fresh_db
    assert db.insert_record(_rec()) is True
    # same hash -> blocked
    assert db.insert_record(_rec()) is False
    assert db.count_records(status="pending") == 1


def test_discard_is_permanent(fresh_db):
    db = fresh_db
    assert db.insert_record(_rec()) is True
    rec = db.list_records(status="pending")[0]
    db.update_record_status(rec["id"], "discarded", reviewer="analyst",
                            notes="off-topic")
    assert db.is_discarded("hash-1")
    # Same payload scraped again must be blocked
    assert db.insert_record(_rec()) is False


def test_approve_flips_status_and_counts(fresh_db):
    db = fresh_db
    db.insert_record(_rec(dedup_hash="h-a"))
    db.insert_record(_rec(dedup_hash="h-b", external_id="ext-2"))
    ids = [r["id"] for r in db.list_records(status="pending")]
    db.update_record_status(ids[0], "approved", reviewer="analyst")
    assert db.count_records(status="approved") == 1
    assert db.count_records(status="pending") == 1


def test_search_and_source_filter(fresh_db):
    db = fresh_db
    db.insert_record(_rec(dedup_hash="h1", title="Gold project news"))
    db.insert_record(_rec(dedup_hash="h2", source="austender",
                          source_group="tenders", title="Copper tender"))
    gold = db.list_records(search="gold")
    assert len(gold) == 1 and "Gold" in gold[0]["title"]
    tenders = db.list_records(source="austender")
    assert len(tenders) == 1 and tenders[0]["source"] == "austender"


def test_distinct_sources(fresh_db):
    db = fresh_db
    db.insert_record(_rec(dedup_hash="h1"))
    db.insert_record(_rec(dedup_hash="h2", source="asx_announcements"))
    assert set(db.distinct_sources()) == {"news_afr", "asx_announcements"}


def test_schedule_crud(fresh_db):
    db = fresh_db
    sid = db.create_schedule("Morning", ["group:tenders"],
                             {"minute": "0", "hour": "6"}, "daily")
    assert db.get_schedule(sid)["name"] == "Morning"
    db.update_schedule(sid, "Morning v2", ["austender"],
                       {"minute": "30", "hour": "7"}, "tweaked")
    assert db.get_schedule(sid)["cron_minute"] == "30"
    db.delete_schedule(sid)
    assert db.get_schedule(sid) is None


def test_scraper_run_lifecycle(fresh_db):
    db = fresh_db
    rid = db.start_scraper_run("austender", triggered_by="test")
    db.finish_scraper_run(rid, "completed", items_found=5, items_new=3)
    row = db.recent_scraper_runs(limit=1)[0]
    assert row["status"] == "completed"
    assert row["items_new"] == 3


def test_schedule_run_with_children(fresh_db):
    db = fresh_db
    sid = db.create_schedule("S", ["austender"], {"minute": "0", "hour": "0"})
    rid = db.start_schedule_run(sid, "S")
    child = db.start_scraper_run("austender", schedule_id=sid,
                                 schedule_run_id=rid)
    db.finish_scraper_run(child, "completed", items_found=2, items_new=2)
    db.finish_schedule_run(rid, "ok", 1, 0, 2, [{"key": "austender"}])
    detail = db.get_schedule_run(rid)
    assert detail["status"] == "ok"
    assert len(detail["scraper_runs"]) == 1


def test_settings_roundtrip(fresh_db):
    db = fresh_db
    db.set_setting("deepseek_api_key", "sk-test")
    db.set_setting("webhook_url", "https://x.example/h")
    assert db.get_setting("deepseek_api_key") == "sk-test"
    assert db.get_setting("missing", "default") == "default"


def test_api_key_lifecycle(fresh_db):
    db = fresh_db
    token = db.create_api_key("analyst-dashboard")
    assert db.validate_api_key(token) is True
    assert db.validate_api_key("wrong") is False
    assert db.validate_api_key("") is False
    key_id = db.list_api_keys()[0]["id"]
    db.revoke_api_key(key_id)
    assert db.validate_api_key(token) is False


def test_restore_from_discarded_removes_block(fresh_db):
    """Restoring a discarded record through the app flow should also free
    its fingerprint (covered via the Flask route in test_flask)."""
    db = fresh_db
    db.insert_record(_rec())
    rec = db.list_records(status="pending")[0]
    db.update_record_status(rec["id"], "discarded")
    # Manual un-discard by deleting key (mirrors what the /restore route does)
    with db.conn() as c:
        c.execute("DELETE FROM discarded_keys WHERE dedup_hash=?",
                  ("hash-1",))
    assert db.is_discarded("hash-1") is False
