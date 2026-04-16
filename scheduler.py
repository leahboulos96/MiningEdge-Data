"""
Flexible scheduling.

A Schedule is a DB row containing:
  - a cron expression (minute/hour/day/month/dow)
  - a list of targets which can be scraper keys OR "group:<name>" entries
  - an enabled flag

When the cron fires, `run_schedule(schedule_id)`:
  - opens a schedule_run report row
  - expands group targets to scraper keys via registry.resolve_targets
  - runs each scraper in isolation - one failure never stops the others
  - finishes the report row with ok/fail counts and a per-scraper summary

The report can be viewed from the dashboard (Schedule Runs page).
"""

import json
import logging
import threading
import traceback
import collections

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import db
import registry

scheduler = BackgroundScheduler(daemon=True)
_started = False
_running_scrapers = {}  # key -> bool, live UI indicator

# ---- Live activity (polled by the dashboard) ----------------------------
# One entry per currently-running scraper run. The entry stores a rolling
# window of the last N log lines plus the in-flight stats.
_LIVE_LOGS = {}          # run_id -> collections.deque[str]
_LIVE_META = {}          # run_id -> dict
_LIVE_LOCK = threading.Lock()
_LIVE_MAX_LINES = 200
_LIVE_MAX_ENTRIES = 50   # total runs kept in memory (FIFO, finished evicted first)


class _LiveLogHandler(logging.Handler):
    """Logging handler that pushes formatted log records into the live-log
    ring buffer for a specific run. One handler instance per run."""
    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s",
                                             datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            return
        with _LIVE_LOCK:
            dq = _LIVE_LOGS.get(self.run_id)
            if dq is None:
                dq = collections.deque(maxlen=_LIVE_MAX_LINES)
                _LIVE_LOGS[self.run_id] = dq
            dq.append(line)


def _live_begin(run_id, scraper_key, schedule_id=None):
    with _LIVE_LOCK:
        _evict_if_full_locked()
        _LIVE_LOGS[run_id] = collections.deque(maxlen=_LIVE_MAX_LINES)
        _LIVE_META[run_id] = {
            "run_id": run_id,
            "scraper": scraper_key,
            "label": registry.label(scraper_key),
            "schedule_id": schedule_id,
            "started_at": db.now_iso(),
            "status": "running",
            "items_found": 0,
            "items_new": 0,
            "items_skipped": 0,
        }


def _evict_if_full_locked():
    """Keep the live panel bounded. Drops the oldest FINISHED runs first; a
    still-running run is never evicted. Caller must hold _LIVE_LOCK."""
    if len(_LIVE_META) < _LIVE_MAX_ENTRIES:
        return
    finished = [(m.get("started_at", ""), rid) for rid, m in _LIVE_META.items()
                if m.get("status") != "running"]
    finished.sort()  # oldest first
    while len(_LIVE_META) >= _LIVE_MAX_ENTRIES and finished:
        _, rid = finished.pop(0)
        _LIVE_META.pop(rid, None)
        _LIVE_LOGS.pop(rid, None)


def _live_end(run_id, status, stats):
    with _LIVE_LOCK:
        meta = _LIVE_META.get(run_id)
        if meta:
            meta["status"] = status
            meta["ended_at"] = db.now_iso()
            meta["items_found"] = stats.get("scraped", 0)
            meta["items_new"] = stats.get("new", 0)
            meta["items_skipped"] = stats.get("skipped", 0)


def live_snapshot():
    """Snapshot used by /api/live. Finished runs remain in the panel so the
    user can review what happened. Memory is bounded via _LIVE_MAX_ENTRIES
    (see _evict_if_full_locked) and via the per-run log deque."""
    with _LIVE_LOCK:
        out = []
        for rid, meta in _LIVE_META.items():
            entry = dict(meta)
            entry["log"] = list(_LIVE_LOGS.get(rid, []))[-60:]
            out.append(entry)
    out.sort(key=lambda e: e.get("started_at", ""), reverse=True)
    return out


def clear_finished_live_runs():
    """Remove every finished entry from the live panel. Running entries are
    kept. Used by the 'clear terminals' button on the dashboard."""
    with _LIVE_LOCK:
        to_drop = [rid for rid, m in _LIVE_META.items()
                   if m.get("status") != "running"]
        for rid in to_drop:
            _LIVE_META.pop(rid, None)
            _LIVE_LOGS.pop(rid, None)
    return len(to_drop)


def start():
    global _started
    if not _started:
        scheduler.start()
        _started = True
        reload_all()


def is_running(key):
    return _running_scrapers.get(key, False)


def running_keys():
    return [k for k, v in _running_scrapers.items() if v]


def _job_id(schedule_id):
    return f"schedule_{schedule_id}"


def _build_trigger(row):
    return CronTrigger(
        minute=row["cron_minute"],
        hour=row["cron_hour"],
        day=row["cron_day"],
        month=row["cron_month"],
        day_of_week=row["cron_dow"],
    )


def reload_all():
    """Sync APScheduler jobs with DB schedules."""
    for job in scheduler.get_jobs():
        if job.id.startswith("schedule_"):
            job.remove()

    for row in db.list_schedules():
        if not row["enabled"]:
            continue
        try:
            scheduler.add_job(
                run_schedule,
                trigger=_build_trigger(row),
                id=_job_id(row["id"]),
                args=[row["id"]],
                replace_existing=True,
            )
        except Exception as e:
            print(f"Schedule {row['id']} skipped - invalid cron: {e}")


def reload_one(schedule_id):
    """Refresh a single schedule's APScheduler job."""
    try:
        scheduler.remove_job(_job_id(schedule_id))
    except Exception:
        pass
    row = db.get_schedule(schedule_id)
    if row and row["enabled"]:
        try:
            scheduler.add_job(
                run_schedule,
                trigger=_build_trigger(row),
                id=_job_id(schedule_id),
                args=[schedule_id],
                replace_existing=True,
            )
        except Exception as e:
            print(f"Schedule {schedule_id} invalid cron: {e}")


def _resolve_targets(scrapers_field):
    if isinstance(scrapers_field, str):
        try:
            scrapers_field = json.loads(scrapers_field)
        except Exception:
            scrapers_field = [scrapers_field]
    return registry.resolve_targets(scrapers_field or [])


def run_single_scraper(key, triggered_by="manual", schedule_id=None, schedule_run_id=None):
    """Run one scraper - used by manual 'Run now' buttons and by run_schedule."""
    if key not in registry.REGISTRY:
        return {"key": key, "status": "error", "error": "unknown scraper"}

    if _running_scrapers.get(key):
        return {"key": key, "status": "skipped", "error": "already running"}

    _running_scrapers[key] = True
    run_id = db.start_scraper_run(key, triggered_by=triggered_by,
                                  schedule_id=schedule_id,
                                  schedule_run_id=schedule_run_id)
    _live_begin(run_id, key, schedule_id=schedule_id)
    handler = _LiveLogHandler(run_id)

    stats = {}
    try:
        scraper = registry.cls(key)()
        scraper.logger.addHandler(handler)
        try:
            scraper.execute(run_id=run_id)
        finally:
            scraper.logger.removeHandler(handler)
        stats = scraper.stats
        status = "error" if stats.get("errors") else "ok"
        _live_end(run_id, status, stats)
        return {
            "key": key,
            "run_id": run_id,
            "status": status,
            "found": stats.get("scraped", 0),
            "new": stats.get("new", 0),
            "skipped": stats.get("skipped", 0),
            "errors": stats.get("errors", 0),
        }
    except Exception as e:
        tb = traceback.format_exc()
        db.finish_scraper_run(run_id, status="error", error_message=f"{e}\n{tb}")
        _live_end(run_id, "error", stats or {})
        return {"key": key, "run_id": run_id, "status": "error", "error": str(e)}
    finally:
        _running_scrapers[key] = False


def run_scrapers_in_background(keys, triggered_by="manual"):
    """Run a list of scrapers one after the other in a background thread.
    Failures in one do not stop the others."""
    def _work():
        for key in keys:
            run_single_scraper(key, triggered_by=triggered_by)
    t = threading.Thread(target=_work, daemon=True)
    t.start()


def run_schedule(schedule_id):
    """Executed when a schedule's cron fires. Captures a schedule_run report."""
    sched = db.get_schedule(schedule_id)
    if not sched:
        return
    if not sched["enabled"]:
        return

    keys = _resolve_targets(sched["scrapers"])
    run_id = db.start_schedule_run(schedule_id, sched["name"])

    ok, failed, total_new = 0, 0, 0
    summary = []

    for key in keys:
        result = run_single_scraper(
            key, triggered_by=f"schedule:{sched['name']}",
            schedule_id=schedule_id, schedule_run_id=run_id,
        )
        summary.append(result)
        if result["status"] == "ok":
            ok += 1
            total_new += result.get("new", 0)
        else:
            failed += 1

    overall = "ok" if failed == 0 else ("partial" if ok > 0 else "error")
    db.finish_schedule_run(run_id, overall, ok, failed, total_new, summary)
    db.mark_schedule_last_run(schedule_id, overall)


def run_schedule_now(schedule_id):
    """Manual 'Run Now' button for a schedule. Runs in a background thread."""
    t = threading.Thread(target=run_schedule, args=(schedule_id,), daemon=True)
    t.start()
