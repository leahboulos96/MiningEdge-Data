"""
Outbound webhook dispatch. When an analyst approves a record the approved
payload is POSTed (in a background thread so the UI stays responsive) to
the webhook URL configured in Settings.
"""

import json
import threading
import requests

import db


def dispatch_approved(record):
    """Fire-and-forget POST to the configured webhook URL, if any."""
    url = db.get_setting("webhook_url")
    if not url:
        return
    secret = db.get_setting("webhook_secret") or ""

    payload = {
        "event": "record.approved",
        "record": {
            "id": record.get("id"),
            "source": record.get("source"),
            "source_group": record.get("source_group"),
            "record_type": record.get("record_type"),
            "external_id": record.get("external_id"),
            "title": record.get("title"),
            "description": record.get("description"),
            "entity_name": record.get("entity_name"),
            "published_date": record.get("published_date"),
            "closing_date": record.get("closing_date"),
            "region": record.get("region"),
            "url": record.get("url"),
            "pdf_url": record.get("pdf_url"),
            "enrichment": record.get("enrichment_data"),
            "ai_summary": record.get("ai_summary"),
            "reviewed_at": record.get("reviewed_at"),
            "reviewed_by": record.get("reviewed_by"),
        },
    }

    def _send():
        try:
            requests.post(
                url,
                json=payload,
                headers={"X-MiningEdge-Secret": secret} if secret else {},
                timeout=20,
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()
