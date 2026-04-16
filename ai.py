"""
DeepSeek AI integration stub.

The client asked us NOT to enable AI yet, but to prepare the plumbing so they
can drop a DeepSeek API key in the Settings page and turn it on.

How to get a DeepSeek key (shown to the user on the Settings page):
  1. Go to https://platform.deepseek.com/
  2. Sign up / log in
  3. Open "API Keys" in the left sidebar
  4. Click "Create new API key", copy the key, paste it in Settings.

When enabled, `enrich_record` will:
  - Build a short prompt with the record title/description
  - Call DeepSeek chat completions
  - Write the result to records.ai_summary and records.enrichment_data

Until a key is saved, `enrich_record` is a no-op.
"""

import json
import requests

import db

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def is_configured():
    return bool(db.get_setting("deepseek_api_key"))


def enrich_record(record):
    """Enrich one record. Returns (ai_summary, enrichment_data) or (None, None)
    when AI is disabled."""
    key = db.get_setting("deepseek_api_key")
    if not key:
        return None, None

    prompt = (
        "You are assisting a mining industry analyst. Summarise the following "
        "record in 3 bullet points and extract: commodity, region, stage, "
        "likely dollar value (if any). Respond as JSON with keys "
        "'summary', 'commodity', 'region', 'stage', 'value_estimate'.\n\n"
        f"TITLE: {record.get('title','')}\n"
        f"SOURCE: {record.get('source','')}\n"
        f"DESCRIPTION: {record.get('description','')}\n"
    )

    try:
        resp = requests.post(
            DEEPSEEK_ENDPOINT,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"raw": content}
        summary = parsed.get("summary") if isinstance(parsed, dict) else content
        return summary, parsed
    except Exception as e:
        return None, {"error": str(e)}
