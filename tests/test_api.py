"""REST API tests: auth + record listing + approve/discard."""


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(db, **overrides):
    base = {
        "source": "news_afr", "source_group": "news", "record_type": "news",
        "external_id": "ext-1", "title": "Sample",
        "description": "", "dedup_hash": "h1",
    }
    base.update(overrides)
    db.insert_record(base)


def test_health_is_public(app_client):
    client, _ = app_client
    assert client.get("/api/v1/health").status_code == 200


def test_read_endpoints_are_open(app_client, fresh_db):
    """Read endpoints were temporarily opened up for in-browser viewing; see
    the security note at the top of api.py. Writes still require a token."""
    client, _ = app_client
    _seed(fresh_db)
    assert client.get("/api/v1/records").status_code == 200
    assert client.get("/api/v1/sources").status_code == 200


def test_writes_still_require_auth(app_client, fresh_db):
    client, _ = app_client
    _seed(fresh_db)
    rid = fresh_db.list_records()[0]["id"]
    assert client.post(f"/api/v1/records/{rid}/approve").status_code == 401
    assert client.post(f"/api/v1/records/{rid}/discard").status_code == 401


def test_revoked_key_rejected_on_writes(app_client, fresh_db):
    client, _ = app_client
    _seed(fresh_db)
    rid = fresh_db.list_records()[0]["id"]
    token = fresh_db.create_api_key("k")
    assert client.post(f"/api/v1/records/{rid}/approve",
                       json={}, headers=_auth(token)).status_code == 200
    fresh_db.revoke_api_key(fresh_db.list_api_keys()[0]["id"])
    _seed(fresh_db, dedup_hash="h2", external_id="ext-2")
    rid2 = [r for r in fresh_db.list_records() if r["dedup_hash"] == "h2"][0]["id"]
    assert client.post(f"/api/v1/records/{rid2}/approve",
                       json={}, headers=_auth(token)).status_code == 401


def test_list_filter_by_status_and_source(app_client, fresh_db):
    client, _ = app_client
    _seed(fresh_db, dedup_hash="h1")
    _seed(fresh_db, dedup_hash="h2", source="austender",
          source_group="tenders", external_id="ext-2")
    rec2 = fresh_db.list_records(source="austender")[0]
    fresh_db.update_record_status(rec2["id"], "approved")

    token = fresh_db.create_api_key("k")
    approved = client.get("/api/v1/records?status=approved",
                          headers=_auth(token)).get_json()
    assert approved["count"] == 1
    assert approved["records"][0]["source"] == "austender"

    by_source = client.get("/api/v1/records?status=pending&source=news_afr",
                           headers=_auth(token)).get_json()
    assert by_source["count"] == 1


def test_api_approve_and_discard(app_client, fresh_db):
    client, _ = app_client
    _seed(fresh_db, dedup_hash="h-approve")
    _seed(fresh_db, dedup_hash="h-discard", external_id="ext-2")
    token = fresh_db.create_api_key("k")

    by_hash = {r["dedup_hash"]: r["id"] for r in fresh_db.list_records()}

    r = client.post(f"/api/v1/records/{by_hash['h-approve']}/approve",
                    json={"reviewer": "bot"}, headers=_auth(token))
    assert r.status_code == 200
    assert fresh_db.get_record(by_hash["h-approve"])["status"] == "approved"

    r = client.post(f"/api/v1/records/{by_hash['h-discard']}/discard",
                    json={"reason": "bad"}, headers=_auth(token))
    assert r.status_code == 200
    assert fresh_db.is_discarded("h-discard")


def test_api_record_detail_and_sources(app_client, fresh_db):
    client, _ = app_client
    _seed(fresh_db)
    token = fresh_db.create_api_key("k")
    rid = fresh_db.list_records()[0]["id"]
    r = client.get(f"/api/v1/records/{rid}", headers=_auth(token))
    assert r.status_code == 200 and r.get_json()["id"] == rid
    r = client.get("/api/v1/sources", headers=_auth(token))
    assert "news_afr" in r.get_json()["sources"]
