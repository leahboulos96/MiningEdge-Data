"""Smoke + behaviour tests for the Flask dashboard."""

import json


def _seed(db, title="Pending record", dedup="hash-1", status="pending"):
    db.insert_record({
        "source": "news_afr", "source_group": "news", "record_type": "news",
        "external_id": "ext-1", "title": title,
        "description": "", "dedup_hash": dedup,
    })
    rec = db.list_records(status="pending")[0]
    if status != "pending":
        db.update_record_status(rec["id"], status)
    return rec


def test_all_pages_render_200(app_client):
    client, _ = app_client
    for path in [
        "/", "/records", "/records?status=approved", "/records?status=discarded",
        "/scrapers", "/schedules", "/schedules/new", "/schedule-runs",
        "/settings", "/files", "/backup", "/logs",
    ]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"


def test_login_required_redirects(app_client):
    client, _ = app_client
    with client.session_transaction() as s:
        s.clear()
    r = client.get("/records")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_approve_record_flow(app_client, fresh_db):
    client, _ = app_client
    rec = _seed(fresh_db)
    r = client.post(f"/records/{rec['id']}/approve",
                    data={"notes": "looks good"}, follow_redirects=True)
    assert r.status_code == 200
    assert fresh_db.get_record(rec["id"])["status"] == "approved"


def test_discard_is_permanent_through_ui(app_client, fresh_db):
    client, _ = app_client
    rec = _seed(fresh_db, dedup="hash-perm")
    client.post(f"/records/{rec['id']}/discard", data={"reason": "off-topic"})
    assert fresh_db.is_discarded("hash-perm")
    # Try inserting same fingerprint again - must be blocked
    assert fresh_db.insert_record({
        "source": "news_afr", "dedup_hash": "hash-perm", "title": "same",
    }) is False


def test_restore_from_discarded_clears_block(app_client, fresh_db):
    client, _ = app_client
    rec = _seed(fresh_db, dedup="hash-r")
    client.post(f"/records/{rec['id']}/discard")
    assert fresh_db.is_discarded("hash-r")
    client.post(f"/records/{rec['id']}/restore")
    assert not fresh_db.is_discarded("hash-r")
    assert fresh_db.get_record(rec["id"])["status"] == "pending"


def test_schedule_create_edit_delete(app_client, fresh_db):
    client, _ = app_client
    # Create
    r = client.post("/schedules/new", data={
        "name": "Daily", "description": "morning",
        "cron_minute": "0", "cron_hour": "6",
        "cron_day": "*", "cron_month": "*", "cron_dow": "*",
        "targets": ["group:tenders"], "enabled": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    rows = fresh_db.list_schedules()
    assert len(rows) == 1 and rows[0]["name"] == "Daily"

    sid = rows[0]["id"]
    client.post(f"/schedules/{sid}/edit", data={
        "name": "Daily v2", "description": "",
        "cron_minute": "30", "cron_hour": "7",
        "cron_day": "*", "cron_month": "*", "cron_dow": "*",
        "targets": ["austender"], "enabled": "on",
    })
    assert fresh_db.get_schedule(sid)["cron_minute"] == "30"
    client.post(f"/schedules/{sid}/delete")
    assert fresh_db.get_schedule(sid) is None


def test_settings_saves_deepseek_and_webhook(app_client, fresh_db):
    client, _ = app_client
    client.post("/settings", data={
        "scrape_do_token": "tok",
        "asx_tickers": "BHP, RIO",
        "deepseek_api_key": "sk-xyz",
        "webhook_url": "https://hook.example/x",
        "webhook_secret": "shh",
    })
    assert fresh_db.get_setting("deepseek_api_key") == "sk-xyz"
    assert fresh_db.get_setting("webhook_url") == "https://hook.example/x"
    assert fresh_db.get_setting("webhook_secret") == "shh"


def test_webhook_fired_on_approval(app_client, fresh_db, monkeypatch):
    import webhooks
    called = {}

    def fake_dispatch(record):
        called["record"] = record

    monkeypatch.setattr(webhooks, "dispatch_approved", fake_dispatch)
    # Also patch the already-imported reference inside app
    from app import app as flask_app
    import app as app_mod
    monkeypatch.setattr(app_mod.webhooks, "dispatch_approved", fake_dispatch)

    client, _ = app_client
    rec = _seed(fresh_db, dedup="hash-wh")
    client.post(f"/records/{rec['id']}/approve", data={"notes": ""})
    assert called.get("record", {}).get("id") == rec["id"]


def test_help_tooltips_present(app_client):
    """At least one help '?' tooltip should appear on the key pages."""
    client, _ = app_client
    for path in ["/", "/records", "/schedules", "/settings"]:
        html = client.get(path).data.decode("utf-8")
        assert 'class="help"' in html, f"missing help tooltip on {path}"
