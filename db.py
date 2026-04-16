"""
SQLite database layer for the unified MiningEdge data platform.

Tables:
  records         - unified normalized records from all sources (tenders, news, ASX)
  discarded_keys  - permanent fingerprints of discarded records so they are never
                    re-ingested even if the record row itself is purged
  scraper_runs    - history of every scraper execution (manual or scheduled)
  schedule_runs   - history of every schedule firing (a schedule can run 1..N scrapers)
  schedules       - user-defined schedules (cron-like) mapped to one scraper or a group
  settings        - key/value configuration store (deepseek key, webhook url, etc.)
  api_keys        - tokens granting access to the REST API
"""

import os
import json
import sqlite3
import secrets
import threading
from datetime import datetime, timezone
from contextlib import contextmanager

import config

DB_PATH = os.path.join(config.BASE_DIR, "miningedge.db")
_lock = threading.Lock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    source_group        TEXT,
    record_type         TEXT,
    external_id         TEXT,
    dedup_hash          TEXT NOT NULL UNIQUE,
    title               TEXT,
    description         TEXT,
    entity_name         TEXT,
    published_date      TEXT,
    closing_date        TEXT,
    region              TEXT,
    url                 TEXT,
    pdf_url             TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    raw_data            TEXT,
    enrichment_data     TEXT,
    ai_summary          TEXT,
    scraped_at          TEXT NOT NULL,
    updated_at          TEXT,
    reviewed_at         TEXT,
    reviewed_by         TEXT,
    review_notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_scraped_at ON records(scraped_at);

CREATE TABLE IF NOT EXISTS discarded_keys (
    dedup_hash  TEXT PRIMARY KEY,
    source      TEXT,
    discarded_at TEXT NOT NULL,
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS scraper_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scraper         TEXT NOT NULL,
    schedule_id     INTEGER,
    schedule_run_id INTEGER,
    triggered_by    TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    status          TEXT NOT NULL,
    items_found     INTEGER DEFAULT 0,
    items_new       INTEGER DEFAULT 0,
    items_skipped   INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_scraper_runs_scraper ON scraper_runs(scraper);
CREATE INDEX IF NOT EXISTS idx_scraper_runs_started ON scraper_runs(started_at);

CREATE TABLE IF NOT EXISTS schedule_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id     INTEGER NOT NULL,
    schedule_name   TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    status          TEXT NOT NULL,
    scrapers_ok     INTEGER DEFAULT 0,
    scrapers_failed INTEGER DEFAULT 0,
    total_new       INTEGER DEFAULT 0,
    summary         TEXT
);

CREATE TABLE IF NOT EXISTS schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    cron_minute     TEXT DEFAULT '0',
    cron_hour       TEXT DEFAULT '6',
    cron_day        TEXT DEFAULT '*',
    cron_month      TEXT DEFAULT '*',
    cron_dow        TEXT DEFAULT '*',
    scrapers        TEXT NOT NULL,
    enabled         INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_run_at     TEXT,
    last_status     TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    token       TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    last_used   TEXT,
    enabled     INTEGER DEFAULT 1
);
"""


@contextmanager
def conn():
    """Yield a sqlite connection. Thread-safe via a global lock."""
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init_db():
    """Create tables on first run. Safe to call repeatedly."""
    with conn() as c:
        c.executescript(SCHEMA)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------- Records ----------------

def is_discarded(dedup_hash):
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM discarded_keys WHERE dedup_hash = ?", (dedup_hash,)
        ).fetchone()
        return row is not None


def record_exists(dedup_hash):
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM records WHERE dedup_hash = ?", (dedup_hash,)
        ).fetchone()
        return row is not None


def insert_record(rec):
    """Insert a normalized record. Returns True if inserted, False if skipped
    (duplicate or previously discarded)."""
    dedup = rec.get("dedup_hash")
    if not dedup:
        return False
    if is_discarded(dedup) or record_exists(dedup):
        return False

    with conn() as c:
        c.execute("""
            INSERT INTO records
                (source, source_group, record_type, external_id, dedup_hash,
                 title, description, entity_name, published_date, closing_date,
                 region, url, pdf_url, status, raw_data, scraped_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """, (
            rec.get("source"),
            rec.get("source_group"),
            rec.get("record_type"),
            rec.get("external_id"),
            dedup,
            rec.get("title"),
            rec.get("description"),
            rec.get("entity_name"),
            rec.get("published_date"),
            rec.get("closing_date"),
            rec.get("region"),
            rec.get("url"),
            rec.get("pdf_url"),
            json.dumps(rec.get("raw_data") or {}, default=str, ensure_ascii=False),
            rec.get("scraped_at") or now_iso(),
            now_iso(),
        ))
    return True


def list_records(status=None, source=None, search=None, limit=200, offset=0):
    sql = "SELECT * FROM records WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"; params.append(status)
    if source:
        sql += " AND source = ?"; params.append(source)
    if search:
        like = f"%{search}%"
        sql += " AND (title LIKE ? OR description LIKE ? OR entity_name LIKE ?)"
        params += [like, like, like]
    sql += " ORDER BY scraped_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def count_records(status=None, source=None):
    sql = "SELECT COUNT(*) AS n FROM records WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"; params.append(status)
    if source:
        sql += " AND source = ?"; params.append(source)
    with conn() as c:
        return c.execute(sql, params).fetchone()["n"]


def get_record(record_id):
    with conn() as c:
        r = c.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return dict(r) if r else None


def update_record_status(record_id, status, reviewer=None, notes=None):
    """Approve or discard a record. Discard also adds a permanent fingerprint."""
    with conn() as c:
        rec = c.execute("SELECT dedup_hash, source FROM records WHERE id = ?",
                        (record_id,)).fetchone()
        if not rec:
            return None
        c.execute("""
            UPDATE records SET status = ?, reviewed_at = ?, reviewed_by = ?,
                   review_notes = ?, updated_at = ?
            WHERE id = ?
        """, (status, now_iso(), reviewer, notes, now_iso(), record_id))

        if status == "discarded":
            c.execute("""
                INSERT OR IGNORE INTO discarded_keys
                    (dedup_hash, source, discarded_at, reason)
                VALUES (?, ?, ?, ?)
            """, (rec["dedup_hash"], rec["source"], now_iso(), notes))
    return True


def update_record_enrichment(record_id, enrichment_data=None, ai_summary=None):
    with conn() as c:
        c.execute("""
            UPDATE records SET enrichment_data = COALESCE(?, enrichment_data),
                               ai_summary = COALESCE(?, ai_summary),
                               updated_at = ?
            WHERE id = ?
        """, (
            json.dumps(enrichment_data, default=str, ensure_ascii=False) if enrichment_data else None,
            ai_summary,
            now_iso(),
            record_id,
        ))


def distinct_sources():
    with conn() as c:
        return [r["source"] for r in c.execute(
            "SELECT DISTINCT source FROM records ORDER BY source").fetchall()]


# ---------------- Scraper run history ----------------

def start_scraper_run(scraper, triggered_by="manual", schedule_id=None, schedule_run_id=None):
    with conn() as c:
        cur = c.execute("""
            INSERT INTO scraper_runs
                (scraper, schedule_id, schedule_run_id, triggered_by, started_at, status)
            VALUES (?, ?, ?, ?, ?, 'running')
        """, (scraper, schedule_id, schedule_run_id, triggered_by, now_iso()))
        return cur.lastrowid


def finish_scraper_run(run_id, status, items_found=0, items_new=0,
                      items_skipped=0, error_message=None):
    with conn() as c:
        c.execute("""
            UPDATE scraper_runs SET ended_at = ?, status = ?,
                   items_found = ?, items_new = ?, items_skipped = ?,
                   error_message = ?
            WHERE id = ?
        """, (now_iso(), status, items_found, items_new, items_skipped,
              error_message, run_id))


def recent_scraper_runs(limit=50, scraper=None):
    sql = "SELECT * FROM scraper_runs"
    params = []
    if scraper:
        sql += " WHERE scraper = ?"; params.append(scraper)
    sql += " ORDER BY started_at DESC LIMIT ?"; params.append(limit)
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def delete_scraper_run(run_id):
    with conn() as c:
        c.execute("DELETE FROM scraper_runs WHERE id = ? AND status != 'running'",
                  (run_id,))


def clear_scraper_runs(older_than_days=None, scraper=None):
    """Bulk cleanup. If older_than_days is given, only deletes finished runs
    older than that. If scraper is given, scopes to one scraper."""
    sql = "DELETE FROM scraper_runs WHERE status != 'running'"
    params = []
    if older_than_days is not None:
        sql += (" AND started_at < datetime('now', ?)")
        params.append(f"-{int(older_than_days)} days")
    if scraper:
        sql += " AND scraper = ?"; params.append(scraper)
    with conn() as c:
        c.execute(sql, params)


# ---------------- Schedules ----------------

def list_schedules():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM schedules ORDER BY id").fetchall()]


def get_schedule(sid):
    with conn() as c:
        r = c.execute("SELECT * FROM schedules WHERE id = ?", (sid,)).fetchone()
        return dict(r) if r else None


def create_schedule(name, scrapers, cron, description="", enabled=True):
    """scrapers: list[str]  cron: dict with keys minute,hour,day,month,dow"""
    with conn() as c:
        cur = c.execute("""
            INSERT INTO schedules
                (name, description, cron_minute, cron_hour, cron_day,
                 cron_month, cron_dow, scrapers, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, description,
            cron.get("minute", "0"), cron.get("hour", "6"),
            cron.get("day", "*"), cron.get("month", "*"),
            cron.get("dow", "*"),
            json.dumps(scrapers),
            1 if enabled else 0,
            now_iso(),
        ))
        return cur.lastrowid


def update_schedule(sid, name, scrapers, cron, description="", enabled=True):
    with conn() as c:
        c.execute("""
            UPDATE schedules SET name = ?, description = ?,
                cron_minute = ?, cron_hour = ?, cron_day = ?, cron_month = ?,
                cron_dow = ?, scrapers = ?, enabled = ?
            WHERE id = ?
        """, (
            name, description,
            cron.get("minute", "0"), cron.get("hour", "6"),
            cron.get("day", "*"), cron.get("month", "*"),
            cron.get("dow", "*"),
            json.dumps(scrapers), 1 if enabled else 0,
            sid,
        ))


def delete_schedule(sid):
    with conn() as c:
        c.execute("DELETE FROM schedules WHERE id = ?", (sid,))


def mark_schedule_last_run(sid, status):
    with conn() as c:
        c.execute("UPDATE schedules SET last_run_at = ?, last_status = ? WHERE id = ?",
                  (now_iso(), status, sid))


# ---------------- Schedule runs (reports) ----------------

def start_schedule_run(schedule_id, schedule_name):
    with conn() as c:
        cur = c.execute("""
            INSERT INTO schedule_runs
                (schedule_id, schedule_name, started_at, status)
            VALUES (?, ?, ?, 'running')
        """, (schedule_id, schedule_name, now_iso()))
        return cur.lastrowid


def finish_schedule_run(run_id, status, ok_count, failed_count, total_new, summary):
    with conn() as c:
        c.execute("""
            UPDATE schedule_runs SET ended_at = ?, status = ?,
                scrapers_ok = ?, scrapers_failed = ?, total_new = ?,
                summary = ?
            WHERE id = ?
        """, (now_iso(), status, ok_count, failed_count, total_new,
              json.dumps(summary, default=str), run_id))


def delete_schedule_run(run_id):
    """Deletes a schedule_run row and all its child scraper_runs."""
    with conn() as c:
        c.execute("DELETE FROM scraper_runs WHERE schedule_run_id = ?", (run_id,))
        c.execute("DELETE FROM schedule_runs WHERE id = ?", (run_id,))


def clear_all_schedule_runs():
    """Wipe every schedule_run (and its child scraper_runs)."""
    with conn() as c:
        c.execute("DELETE FROM scraper_runs WHERE schedule_run_id IS NOT NULL")
        c.execute("DELETE FROM schedule_runs")


def wipe_all_records(also_clear_discarded_keys=False):
    """Danger-zone: delete every record. Optionally also clear the permanent
    'discarded' fingerprints so previously-discarded items can be scraped
    again. Returns counts for the flash message."""
    with conn() as c:
        n_rec = c.execute("SELECT COUNT(*) AS n FROM records").fetchone()["n"]
        c.execute("DELETE FROM records")
        n_dk = 0
        if also_clear_discarded_keys:
            n_dk = c.execute("SELECT COUNT(*) AS n FROM discarded_keys").fetchone()["n"]
            c.execute("DELETE FROM discarded_keys")
        return n_rec, n_dk


def recent_schedule_runs(limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM schedule_runs ORDER BY started_at DESC LIMIT ?",
            (limit,)).fetchall()]


def get_schedule_run(run_id):
    with conn() as c:
        r = c.execute("SELECT * FROM schedule_runs WHERE id = ?",
                      (run_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["scraper_runs"] = [dict(x) for x in c.execute(
            "SELECT * FROM scraper_runs WHERE schedule_run_id = ? ORDER BY id",
            (run_id,)).fetchall()]
        return d


# ---------------- Settings key/value ----------------

def get_setting(key, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except Exception:
            return r["value"]


def set_setting(key, value):
    with conn() as c:
        c.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, json.dumps(value, default=str)))


def all_settings():
    with conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except Exception:
            out[r["key"]] = r["value"]
    return out


# ---------------- API keys ----------------

def list_api_keys():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM api_keys ORDER BY id DESC").fetchall()]


def create_api_key(name):
    token = secrets.token_urlsafe(32)
    with conn() as c:
        c.execute("""
            INSERT INTO api_keys (name, token, created_at, enabled)
            VALUES (?, ?, ?, 1)
        """, (name, token, now_iso()))
    return token


def revoke_api_key(key_id):
    with conn() as c:
        c.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))


def validate_api_key(token):
    if not token:
        return False
    with conn() as c:
        r = c.execute(
            "SELECT id FROM api_keys WHERE token = ? AND enabled = 1", (token,)
        ).fetchone()
        if r:
            c.execute("UPDATE api_keys SET last_used = ? WHERE id = ?",
                      (now_iso(), r["id"]))
            return True
    return False
