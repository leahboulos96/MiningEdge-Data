"""
REST API for external integrations.

Endpoints:
  GET  /api/v1/health                      - always open, no auth
  GET  /api/v1/records?status=...          - OPEN for viewing (see note below)
  GET  /api/v1/records/<id>                - OPEN for viewing
  GET  /api/v1/sources                     - OPEN for viewing
  GET  /api/v1/records/export?format=...   - OPEN for viewing / downloading
  GET  /api/v1/live                        - OPEN for viewing
  POST /api/v1/records/<id>/approve        - requires Bearer token
  POST /api/v1/records/<id>/discard        - requires Bearer token

================================================================================
!! SECURITY NOTE - READ BEFORE DEPLOYING !!
================================================================================
The read-only GET endpoints above are currently OPEN (no API key required) so
the "API for this view" URLs shown on the /records page can be pasted directly
into a browser and inspected. This is INTENTIONALLY INSECURE FOR NOW - it is
just for viewing / demoing data from the browser.

Implications:
  - Anyone who can reach the server can read every record (including pending
    and discarded ones), all sources, and live scraper logs.
  - There is no rate limiting. The /records/export endpoint will happily
    stream the entire database to any caller.

The write endpoints (approve, discard) STILL require a valid bearer token -
they were not changed, so no visitor can mutate the review queue.

Before real deployment you MUST:
  1. Put @require_api_key back on list_records, get_record, list_sources,
     export_records, and live.
  2. Remove the "Open for viewing" wording from templates/records.html.
================================================================================
"""

from functools import wraps
from flask import Blueprint, request, jsonify, Response

import db
import exports
import scheduler as sched_mod

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def require_api_key(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        auth = request.headers.get("Authorization", "")
        token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else request.args.get("api_key")
        if not db.validate_api_key(token):
            return jsonify({"error": "invalid or missing API key"}), 401
        return fn(*a, **kw)
    return wrapped


@api_bp.route("/health")
def health():
    return jsonify({"ok": True})


@api_bp.route("/records")
def list_records():
    # OPEN - see security note at top of file.
    status = request.args.get("status", "approved")
    source = request.args.get("source")
    search = request.args.get("q")
    limit = min(int(request.args.get("limit", 100)), 1000)
    offset = int(request.args.get("offset", 0))
    rows = db.list_records(status=status, source=source, search=search,
                           limit=limit, offset=offset)
    return jsonify({
        "count": len(rows),
        "total": db.count_records(status=status, source=source),
        "records": rows,
    })


@api_bp.route("/records/<int:record_id>")
def get_record(record_id):
    # OPEN - see security note at top of file.
    rec = db.get_record(record_id)
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify(rec)


@api_bp.route("/sources")
def list_sources():
    # OPEN - see security note at top of file.
    return jsonify({"sources": db.distinct_sources()})


@api_bp.route("/records/<int:record_id>/approve", methods=["POST"])
@require_api_key
def approve(record_id):
    body = request.get_json(silent=True) or {}
    ok = db.update_record_status(
        record_id, "approved",
        reviewer=body.get("reviewer", "api"),
        notes=body.get("notes"),
    )
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@api_bp.route("/records/export")
def export_records():
    """Download a filtered slice of the unified records table.
    Params: format=json|csv|xlsx (default json), status, source, q.
    OPEN - see security note at top of file."""
    try:
        body, mime, fname = exports.build_export(
            request.args.get("format", "json"),
            status=request.args.get("status"),
            source=request.args.get("source"),
            search=request.args.get("q"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return Response(body, mimetype=mime,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_bp.route("/live")
def live():
    """Current running scrapers + recent log lines (JSON). Polled by the
    dashboard every ~1.5s. OPEN - see security note at top of file."""
    return jsonify({"runs": sched_mod.live_snapshot()})


@api_bp.route("/records/<int:record_id>/discard", methods=["POST"])
@require_api_key
def discard(record_id):
    body = request.get_json(silent=True) or {}
    ok = db.update_record_status(
        record_id, "discarded",
        reviewer=body.get("reviewer", "api"),
        notes=body.get("reason"),
    )
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})
