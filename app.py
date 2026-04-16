"""
Flask dashboard for the MiningEdge data platform.

Sections:
  /                    - overview dashboard (run counts, last schedule runs)
  /records             - review queue (pending / approved / discarded tabs)
  /records/<id>        - record detail with approve / discard / enrich actions
  /scrapers            - list every registered scraper, run manually, see history
  /schedules           - list / create / edit / delete schedules, view reports
  /schedules/<id>      - schedule edit form
  /schedule-runs       - run history with per-scraper breakdown
  /settings            - scrape.do token, ASX tickers, ICN cookies, DeepSeek key,
                         webhook URL + secret, API keys
  /logs, /backup       - unchanged from previous version

API: /api/v1/* (see api.py)
"""

import os
import io
import re
import csv
import json
import zipfile
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    send_file, jsonify, Response,
)

import config
import db
import registry
import scheduler as sched_mod
import webhooks
import ai
import exports
from api import api_bp


app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.register_blueprint(api_bp)

SETTINGS_FILE = os.path.join(config.BASE_DIR, "settings.json")


# ---------------- Auth ----------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- Legacy file-based settings (kept for scrape.do/ASX tickers) ---

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "scrape_do_token": config.SCRAPE_DO_TOKEN,
        "asx_tickers": config.ASX_TICKERS,
        "enabled_scrapers": registry.all_keys(),
    }


def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def apply_runtime_settings(s):
    config.SCRAPE_DO_TOKEN = s.get("scrape_do_token", config.SCRAPE_DO_TOKEN)
    config.ASX_TICKERS = s.get("asx_tickers", config.ASX_TICKERS)


# ---------------- Dashboard ----------------

@app.route("/")
@login_required
def dashboard():
    pending = db.count_records(status="pending")
    approved = db.count_records(status="approved")
    discarded = db.count_records(status="discarded")
    recent_schedule = db.recent_schedule_runs(limit=5)
    recent_scrapers = db.recent_scraper_runs(limit=10)
    return render_template(
        "dashboard.html",
        registry=registry.REGISTRY,
        groups=registry.groups(),
        running=sched_mod.running_keys(),
        pending=pending, approved=approved, discarded=discarded,
        recent_schedule=recent_schedule,
        recent_scrapers=recent_scrapers,
    )


# ---------------- Scrapers list + manual run ----------------

@app.route("/scrapers")
@login_required
def scrapers_page():
    runs_by_key = {}
    for r in db.recent_scraper_runs(limit=200):
        runs_by_key.setdefault(r["scraper"], []).append(r)
    return render_template(
        "scrapers.html",
        registry=registry.REGISTRY,
        groups=registry.groups(),
        running=sched_mod.running_keys(),
        runs_by_key=runs_by_key,
    )


@app.route("/run/<key>", methods=["POST", "GET"])
@login_required
def run_scraper(key):
    if key == "all":
        sched_mod.run_scrapers_in_background(registry.all_keys(),
                                             triggered_by=f"manual:{session.get('username')}")
        flash("All scrapers started in background", "success")
    elif key.startswith("group:"):
        group = key.split(":", 1)[1]
        keys = registry.groups().get(group, [])
        sched_mod.run_scrapers_in_background(keys,
                                             triggered_by=f"manual:{session.get('username')}")
        flash(f"Running {len(keys)} {group} scrapers", "success")
    elif key in registry.REGISTRY:
        sched_mod.run_scrapers_in_background([key],
                                             triggered_by=f"manual:{session.get('username')}")
        flash(f"{registry.label(key)} started", "success")
    else:
        flash("Unknown scraper", "error")
    return redirect(request.referrer or url_for("scrapers_page"))


@app.route("/status")
@login_required
def status_api():
    return jsonify({
        "running": sched_mod.running_keys(),
        "pending": db.count_records(status="pending"),
    })


@app.route("/live.json")
@login_required
def live_json():
    """Session-authenticated live feed for the dashboard (no API key needed)."""
    return jsonify({"runs": sched_mod.live_snapshot()})


@app.route("/live/clear", methods=["POST"])
@login_required
def live_clear():
    """Dismiss every FINISHED terminal from the live panel. Running scrapers
    are kept. Called by the 'Clear finished' button on the dashboard."""
    n = sched_mod.clear_finished_live_runs()
    return jsonify({"cleared": n})


# ----------- Delete run history rows -----------

@app.route("/scraper-runs/<int:run_id>/delete", methods=["POST"])
@login_required
def delete_scraper_run_route(run_id):
    db.delete_scraper_run(run_id)
    flash("Run removed", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/scraper-runs/clear", methods=["POST"])
@login_required
def clear_scraper_runs_route():
    days = request.form.get("older_than_days") or None
    scraper = request.form.get("scraper") or None
    db.clear_scraper_runs(older_than_days=int(days) if days else None,
                          scraper=scraper)
    flash("History cleared", "success")
    return redirect(request.referrer or url_for("scrapers_page"))


@app.route("/schedule-runs/<int:run_id>/delete", methods=["POST"])
@login_required
def delete_schedule_run_route(run_id):
    db.delete_schedule_run(run_id)
    flash("Schedule run removed", "success")
    return redirect(request.referrer or url_for("schedule_runs_page"))


# ----------- Danger zone bulk wipes -----------
# These require `?confirm=yes` in the POST body to guard against accidental
# CSRF-style triggers. The UI always double-confirms with JS.

def _confirmed():
    return request.form.get("confirm") == "yes"


@app.route("/records/wipe-all", methods=["POST"])
@login_required
def wipe_all_records_route():
    if not _confirmed():
        flash("Confirmation missing - nothing deleted.", "error")
        return redirect(url_for("records_page"))
    also_discarded = "clear_discarded_keys" in request.form
    n_rec, n_dk = db.wipe_all_records(also_clear_discarded_keys=also_discarded)
    msg = f"Deleted {n_rec} records"
    if n_dk:
        msg += f" and cleared {n_dk} permanent discard fingerprints"
    flash(msg, "success")
    return redirect(url_for("records_page"))


@app.route("/logs/wipe-all", methods=["POST"])
@login_required
def wipe_all_logs():
    if not _confirmed():
        flash("Confirmation missing.", "error")
        return redirect(url_for("logs"))
    n = 0
    if os.path.exists(config.LOGS_DIR):
        for fn in os.listdir(config.LOGS_DIR):
            if fn.endswith(".log"):
                os.remove(os.path.join(config.LOGS_DIR, fn))
                n += 1
    flash(f"Deleted {n} log files", "success")
    return redirect(url_for("logs"))


@app.route("/scraper-runs/wipe-all", methods=["POST"])
@login_required
def wipe_all_scraper_runs():
    if not _confirmed():
        flash("Confirmation missing.", "error")
        return redirect(url_for("scrapers_page"))
    db.clear_scraper_runs()  # all finished runs
    flash("All scraper runs cleared", "success")
    return redirect(request.referrer or url_for("scrapers_page"))


@app.route("/schedule-runs/wipe-all", methods=["POST"])
@login_required
def wipe_all_schedule_runs():
    if not _confirmed():
        flash("Confirmation missing.", "error")
        return redirect(url_for("schedule_runs_page"))
    db.clear_all_schedule_runs()
    flash("All schedule runs cleared", "success")
    return redirect(url_for("schedule_runs_page"))


# ---------------- Review queue ----------------

@app.route("/records")
@login_required
def records_page():
    status = request.args.get("status", "pending")
    source = request.args.get("source") or None
    search = request.args.get("q") or None
    page = max(1, int(request.args.get("page", 1)))
    limit = 50
    offset = (page - 1) * limit

    records = db.list_records(status=status, source=source, search=search,
                              limit=limit, offset=offset)
    total = db.count_records(status=status, source=source)

    return render_template(
        "records.html",
        records=records,
        status=status,
        source=source,
        search=search or "",
        sources=db.distinct_sources(),
        registry=registry.REGISTRY,
        page=page,
        total=total,
        limit=limit,
        counts={
            "pending": db.count_records(status="pending"),
            "approved": db.count_records(status="approved"),
            "discarded": db.count_records(status="discarded"),
        },
    )


@app.route("/records/export")
@login_required
def export_records_route():
    """Download filtered records from the UI. Accepts the same filters as
    /records (status, source, q) plus ?format=json|csv|xlsx."""
    try:
        body, mime, fname = exports.build_export(
            request.args.get("format", "csv"),
            status=request.args.get("status"),
            source=request.args.get("source"),
            search=request.args.get("q"),
        )
    except ValueError as e:
        flash(f"Export error: {e}", "error")
        return redirect(url_for("records_page"))
    return Response(body, mimetype=mime,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.route("/records/<int:record_id>")
@login_required
def record_detail(record_id):
    rec = db.get_record(record_id)
    if not rec:
        flash("Record not found", "error")
        return redirect(url_for("records_page"))
    try:
        rec["raw_data_parsed"] = json.loads(rec.get("raw_data") or "{}")
    except Exception:
        rec["raw_data_parsed"] = {}
    try:
        rec["enrichment_parsed"] = json.loads(rec.get("enrichment_data") or "{}")
    except Exception:
        rec["enrichment_parsed"] = {}
    return render_template("record_detail.html", rec=rec,
                           ai_enabled=ai.is_configured())


@app.route("/records/<int:record_id>/approve", methods=["POST"])
@login_required
def approve_record(record_id):
    notes = request.form.get("notes", "")
    db.update_record_status(record_id, "approved",
                            reviewer=session.get("username"), notes=notes)
    rec = db.get_record(record_id)
    if rec:
        webhooks.dispatch_approved(rec)
    flash("Record approved", "success")
    return redirect(request.referrer or url_for("records_page"))


@app.route("/records/<int:record_id>/discard", methods=["POST"])
@login_required
def discard_record(record_id):
    reason = request.form.get("reason", "")
    db.update_record_status(record_id, "discarded",
                            reviewer=session.get("username"), notes=reason)
    flash("Record discarded (will not be re-ingested)", "success")
    return redirect(request.referrer or url_for("records_page"))


@app.route("/records/<int:record_id>/restore", methods=["POST"])
@login_required
def restore_record(record_id):
    """Move a discarded/approved record back to pending."""
    rec = db.get_record(record_id)
    if rec:
        with db.conn() as c:
            c.execute("UPDATE records SET status='pending', reviewed_at=NULL, "
                      "reviewed_by=NULL WHERE id=?", (record_id,))
            if rec["status"] == "discarded":
                c.execute("DELETE FROM discarded_keys WHERE dedup_hash=?",
                          (rec["dedup_hash"],))
        flash("Record restored to pending", "success")
    return redirect(request.referrer or url_for("records_page"))


@app.route("/records/<int:record_id>/enrich", methods=["POST"])
@login_required
def enrich_record(record_id):
    if not ai.is_configured():
        flash("DeepSeek API key not set. Configure it in Settings.", "error")
        return redirect(url_for("record_detail", record_id=record_id))
    rec = db.get_record(record_id)
    if not rec:
        flash("Record not found", "error")
        return redirect(url_for("records_page"))
    summary, data = ai.enrich_record(rec)
    db.update_record_enrichment(record_id, enrichment_data=data, ai_summary=summary)
    flash("AI enrichment complete", "success")
    return redirect(url_for("record_detail", record_id=record_id))


# ---------------- Schedules ----------------

@app.route("/schedules")
@login_required
def schedules_page():
    rows = db.list_schedules()
    for r in rows:
        try:
            r["scrapers_list"] = json.loads(r["scrapers"])
        except Exception:
            r["scrapers_list"] = []
    return render_template("schedules.html", schedules=rows,
                           registry=registry.REGISTRY, groups=registry.groups())


@app.route("/schedules/new", methods=["GET", "POST"])
@login_required
def new_schedule():
    if request.method == "POST":
        sid = _save_schedule_from_form(None)
        sched_mod.reload_one(sid)
        flash("Schedule created", "success")
        return redirect(url_for("schedules_page"))
    return render_template("schedule_edit.html", row=None,
                           registry=registry.REGISTRY, groups=registry.groups())


@app.route("/schedules/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def edit_schedule(sid):
    row = db.get_schedule(sid)
    if not row:
        flash("Schedule not found", "error")
        return redirect(url_for("schedules_page"))
    if request.method == "POST":
        _save_schedule_from_form(sid)
        sched_mod.reload_one(sid)
        flash("Schedule updated", "success")
        return redirect(url_for("schedules_page"))
    try:
        row["scrapers_list"] = json.loads(row["scrapers"])
    except Exception:
        row["scrapers_list"] = []
    return render_template("schedule_edit.html", row=row,
                           registry=registry.REGISTRY, groups=registry.groups())


def _save_schedule_from_form(sid):
    name = request.form.get("name", "").strip() or "Unnamed schedule"
    description = request.form.get("description", "").strip()
    enabled = "enabled" in request.form
    cron = {
        "minute": request.form.get("cron_minute", "0").strip() or "0",
        "hour":   request.form.get("cron_hour", "6").strip() or "6",
        "day":    request.form.get("cron_day", "*").strip() or "*",
        "month":  request.form.get("cron_month", "*").strip() or "*",
        "dow":    request.form.get("cron_dow", "*").strip() or "*",
    }
    targets = request.form.getlist("targets")
    if not targets:
        targets = ["group:tenders"]
    if sid is None:
        return db.create_schedule(name, targets, cron, description, enabled)
    db.update_schedule(sid, name, targets, cron, description, enabled)
    return sid


@app.route("/schedules/<int:sid>/delete", methods=["POST"])
@login_required
def delete_schedule(sid):
    db.delete_schedule(sid)
    try:
        sched_mod.scheduler.remove_job(sched_mod._job_id(sid))
    except Exception:
        pass
    flash("Schedule deleted", "success")
    return redirect(url_for("schedules_page"))


@app.route("/schedules/<int:sid>/run-now", methods=["POST"])
@login_required
def run_schedule_now(sid):
    sched_mod.run_schedule_now(sid)
    flash("Schedule run triggered in background", "success")
    return redirect(url_for("schedules_page"))


@app.route("/schedule-runs")
@login_required
def schedule_runs_page():
    runs = db.recent_schedule_runs(limit=100)
    return render_template("schedule_runs.html", runs=runs)


@app.route("/schedule-runs/<int:run_id>")
@login_required
def schedule_run_detail(run_id):
    run = db.get_schedule_run(run_id)
    if not run:
        flash("Run not found", "error")
        return redirect(url_for("schedule_runs_page"))
    try:
        run["summary_parsed"] = json.loads(run.get("summary") or "[]")
    except Exception:
        run["summary_parsed"] = []
    return render_template("schedule_run_detail.html", run=run,
                           registry=registry.REGISTRY)


# ---------------- Logs / files / backup (unchanged) ----------------

def get_output_files():
    files = []
    if os.path.exists(config.OUTPUT_DIR):
        for fn in sorted(os.listdir(config.OUTPUT_DIR), reverse=True):
            if fn.endswith(".json"):
                path = os.path.join(config.OUTPUT_DIR, fn)
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        count = len(data) if isinstance(data, list) else 0
                except Exception:
                    count = 0
                files.append({"name": fn, "size": size, "modified": mtime, "records": count})
    return files


def get_log_files():
    files = []
    if os.path.exists(config.LOGS_DIR):
        for fn in sorted(os.listdir(config.LOGS_DIR), reverse=True):
            if fn.endswith(".log"):
                path = os.path.join(config.LOGS_DIR, fn)
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
                files.append({"name": fn, "size": size, "modified": mtime})
    return files


@app.route("/logs")
@login_required
def logs():
    log_files = get_log_files()
    selected = request.args.get("file", "")
    content = ""
    if selected:
        path = os.path.join(config.LOGS_DIR, selected)
        if os.path.exists(path) and selected.endswith(".log"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
    return render_template("logs.html", log_files=log_files, selected=selected, content=content)


@app.route("/files")
@login_required
def files_page():
    return render_template("files.html", output_files=get_output_files())


@app.route("/download/<filename>")
@login_required
def download_output(filename):
    path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.exists(path) and filename.endswith(".json"):
        return send_file(path, as_attachment=True)
    flash("File not found", "error")
    return redirect(url_for("files_page"))


@app.route("/download-csv/<filename>")
@login_required
def download_csv(filename):
    path = os.path.join(config.OUTPUT_DIR, filename)
    if not os.path.exists(path) or not filename.endswith(".json"):
        flash("File not found", "error")
        return redirect(url_for("files_page"))
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        flash("No data to export", "error")
        return redirect(url_for("files_page"))
    all_keys = []
    seen = set()
    for row in data:
        for k in row.keys():
            if k not in seen:
                all_keys.append(k); seen.add(k)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    for row in data:
        writer.writerow({k: str(v) if v is not None else "" for k, v in row.items()})
    csv_name = filename.replace(".json", ".csv")
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={csv_name}"})


@app.route("/view/<filename>")
@login_required
def view_output(filename):
    path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.exists(path) and filename.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pretty = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        count = len(data) if isinstance(data, list) else 0
        return render_template("view_json.html", filename=filename, content=pretty, count=count)
    flash("File not found", "error")
    return redirect(url_for("files_page"))


@app.route("/delete/output/<filename>")
@login_required
def delete_output(filename):
    path = os.path.join(config.OUTPUT_DIR, filename)
    if os.path.exists(path) and filename.endswith(".json"):
        os.remove(path)
        flash(f"Deleted {filename}", "success")
    return redirect(url_for("files_page"))


@app.route("/delete/log/<filename>")
@login_required
def delete_log(filename):
    path = os.path.join(config.LOGS_DIR, filename)
    if os.path.exists(path) and filename.endswith(".log"):
        os.remove(path)
        flash(f"Deleted {filename}", "success")
    return redirect(url_for("logs"))


# ---------------- Groups (dynamic) ----------------

@app.route("/groups")
@login_required
def groups_page():
    return render_template("groups.html", groups=registry.groups(),
                           registry_items=registry.REGISTRY)


@app.route("/groups/new", methods=["GET", "POST"])
@login_required
def new_group():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        scrapers = request.form.getlist("scrapers")
        if not name:
            flash("Group name is required", "error")
            return redirect(url_for("new_group"))
        registry.save_group(name, scrapers)
        flash(f"Group '{name}' created", "success")
        return redirect(url_for("groups_page"))
    return render_template("group_edit.html", name=None, scrapers=[],
                           registry_items=registry.REGISTRY)


@app.route("/groups/<name>/edit", methods=["GET", "POST"])
@login_required
def edit_group(name):
    current = registry.groups().get(name, [])
    if request.method == "POST":
        new_name = request.form.get("name", "").strip() or name
        scrapers = request.form.getlist("scrapers")
        if new_name != name:
            registry.rename_group(name, new_name)
        registry.save_group(new_name, scrapers)
        flash(f"Group '{new_name}' saved", "success")
        return redirect(url_for("groups_page"))
    return render_template("group_edit.html", name=name, scrapers=current,
                           registry_items=registry.REGISTRY)


@app.route("/groups/<name>/delete", methods=["POST"])
@login_required
def delete_group_route(name):
    registry.delete_group(name)
    flash(f"Group '{name}' deleted", "success")
    return redirect(url_for("groups_page"))


# ---------------- Settings ----------------

def load_icn_cookies():
    if os.path.exists(config.ICN_COOKIES_FILE):
        try:
            with open(config.ICN_COOKIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_icn_cookies(cookies):
    with open(config.ICN_COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    current = load_settings()

    if request.method == "POST":
        current["scrape_do_token"] = request.form.get("scrape_do_token", current.get("scrape_do_token", ""))
        tickers_raw = request.form.get("asx_tickers", "")
        if tickers_raw.strip():
            current["asx_tickers"] = [t.strip().upper() for t in tickers_raw.replace("\n", ",").split(",") if t.strip()]

        # ICN cookies
        icn_phpsessid = request.form.get("icn_phpsessid", "").strip()
        icn_remember_tfa = request.form.get("icn_remember_tfa", "").strip()
        icn_xsrf = request.form.get("icn_xsrf", "").strip()
        icn_session = request.form.get("icn_session", "").strip()
        if icn_phpsessid and icn_session:
            cookies = {
                "PHPSESSID": icn_phpsessid,
                "remember_tfa_gateway": icn_remember_tfa,
                "XSRF-TOKEN": icn_xsrf,
                "gateway_by_icn_session": icn_session,
            }
            save_icn_cookies({k: v for k, v in cookies.items() if v})

        save_settings(current)
        apply_runtime_settings(current)

        # DB-backed settings (DeepSeek + webhook)
        db.set_setting("deepseek_api_key", request.form.get("deepseek_api_key", "").strip())
        db.set_setting("webhook_url",      request.form.get("webhook_url", "").strip())
        db.set_setting("webhook_secret",   request.form.get("webhook_secret", "").strip())

        flash("Settings saved", "success")
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        settings=current,
        icn_cookies=load_icn_cookies(),
        deepseek_key=db.get_setting("deepseek_api_key", "") or "",
        webhook_url=db.get_setting("webhook_url", "") or "",
        webhook_secret=db.get_setting("webhook_secret", "") or "",
        api_keys=db.list_api_keys(),
    )


@app.route("/settings/api-keys/new", methods=["POST"])
@login_required
def new_api_key():
    name = request.form.get("name", "unnamed").strip() or "unnamed"
    token = db.create_api_key(name)
    flash(f"API key created. Copy it now (shown once): {token}", "success")
    return redirect(url_for("settings"))


@app.route("/settings/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_api_key(key_id):
    db.revoke_api_key(key_id)
    flash("API key revoked", "success")
    return redirect(url_for("settings"))


# ---------------- Backup (kept, simplified) ----------------

@app.route("/backup")
@login_required
def backup():
    output_count = len([f for f in os.listdir(config.OUTPUT_DIR) if f.endswith(".json")]) if os.path.exists(config.OUTPUT_DIR) else 0
    log_count = len([f for f in os.listdir(config.LOGS_DIR) if f.endswith(".log")]) if os.path.exists(config.LOGS_DIR) else 0
    has_db = os.path.exists(db.DB_PATH)
    return render_template("backup.html", output_count=output_count,
                           log_count=log_count, has_db=has_db)


@app.route("/backup/export")
@login_required
def backup_export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(config.OUTPUT_DIR):
            for fn in sorted(os.listdir(config.OUTPUT_DIR)):
                if fn.endswith(".json"):
                    zf.write(os.path.join(config.OUTPUT_DIR, fn), f"output/{fn}")
        if os.path.exists(config.LOGS_DIR):
            for fn in sorted(os.listdir(config.LOGS_DIR)):
                if fn.endswith(".log"):
                    zf.write(os.path.join(config.LOGS_DIR, fn), f"logs/{fn}")
        if os.path.exists(db.DB_PATH):
            zf.write(db.DB_PATH, "miningedge.db")
        if os.path.exists(SETTINGS_FILE):
            zf.write(SETTINGS_FILE, "settings.json")
        if os.path.exists(config.ICN_COOKIES_FILE):
            zf.write(config.ICN_COOKIES_FILE, "icn_cookies.json")
    buf.seek(0)
    name = f"miningedge_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=name)


# ---------------- Startup ----------------

db.init_db()
_saved = load_settings()
apply_runtime_settings(_saved)
sched_mod.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
