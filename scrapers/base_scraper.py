import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import config
import db


class BaseScraper:
    """Base class for all scrapers with proxy support, retry, logging, and
    unified-database persistence.

    Subclasses must:
      - set `name` (unique key, matches registry.REGISTRY key)
      - implement `run()` returning a list of raw source-shaped dicts
      - implement `normalize(raw)` returning a dict with the unified fields:
            source, source_group, record_type, external_id, title,
            description, entity_name, published_date, closing_date,
            region, url, pdf_url, raw_data (optional), dedup_fields (optional)
        Either provide `dedup_fields` (list of values hashed to form the key)
        or the default `external_id + source` is used.
    """

    name = "base"
    source_group = "other"     # tenders / asx / news
    record_type = "record"     # tender / announcement / news

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.today_compact = datetime.now().strftime("%Y%m%d")
        self.logger = self._setup_logger()
        self.stats = {"scraped": 0, "errors": 0, "start_time": None, "end_time": None}

    def _setup_logger(self):
        logger = logging.getLogger(self.name)
        logger.setLevel(logging.DEBUG)
        logger.handlers = []

        log_file = os.path.join(config.LOGS_DIR, f"{self.name}_{self.today}.log")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        fh.setFormatter(fmt)
        ch.setFormatter(fmt)

        logger.addHandler(fh)
        logger.addHandler(ch)
        return logger

    def _proxy_url(self, url):
        """Build scrape.do proxy URL."""
        return f"{config.SCRAPE_DO_BASE}?token={config.SCRAPE_DO_TOKEN}&url={quote_plus(url)}"

    def fetch(self, url, method="GET", data=None, json_data=None, headers=None, use_proxy=True):
        """Fetch URL with retry logic. Returns requests.Response or None."""
        target = self._proxy_url(url) if use_proxy else url

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                kwargs = {"timeout": 60}
                if headers:
                    kwargs["headers"] = headers
                if data:
                    kwargs["data"] = data
                if json_data:
                    kwargs["json"] = json_data

                if method.upper() == "POST":
                    resp = self.session.post(target, **kwargs)
                else:
                    resp = self.session.get(target, **kwargs)

                if resp.status_code == 200:
                    return resp

                # Don't retry client errors (4xx) - they won't succeed on retry
                if 400 <= resp.status_code < 500:
                    self.logger.warning(f"HTTP {resp.status_code} for {url} (not retrying client error)")
                    self.stats["errors"] += 1
                    return None

                self.logger.warning(
                    f"HTTP {resp.status_code} for {url} (attempt {attempt}/{config.MAX_RETRIES})"
                )
            except requests.RequestException as e:
                self.logger.warning(
                    f"Request error for {url} (attempt {attempt}/{config.MAX_RETRIES}): {e}"
                )

            if attempt < config.MAX_RETRIES:
                wait = config.RETRY_BACKOFF * (2 ** (attempt - 1))
                self.logger.debug(f"Retrying in {wait}s...")
                time.sleep(wait)

        self.logger.error(f"Failed after {config.MAX_RETRIES} attempts: {url}")
        self.stats["errors"] += 1
        return None

    def parse_html(self, html_text):
        """Parse HTML string into BeautifulSoup object."""
        return BeautifulSoup(html_text, "lxml")

    def parse_xml(self, xml_text):
        """Parse XML string into BeautifulSoup object."""
        return BeautifulSoup(xml_text, "xml")

    def save_output(self, data, filename=None):
        """Save data list as JSON to output directory."""
        if filename is None:
            filename = f"{self.name}_{self.today_compact}.json"
        path = os.path.join(config.OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        self.logger.info(f"Saved {len(data)} records to {path}")
        return path

    def now_iso(self):
        """Current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def run(self):
        """Override in subclass. Should return list of raw dicts."""
        raise NotImplementedError

    # Default field mapping from legacy per-scraper output to unified schema.
    # Each unified key maps to a list of candidate raw keys; the first one
    # present on the raw record wins. Subclasses can extend FIELD_MAP or
    # override normalize() entirely.
    FIELD_MAP = {
        "external_id":    ["tender_id_external", "external_id", "id", "ticker"],
        "title":          ["title", "announcement_title", "headline"],
        "description":    ["description_raw", "description", "snippet_raw", "summary"],
        "entity_name":    ["issuing_entity_name", "company_name_raw", "entity_name", "publisher"],
        "published_date": ["published_date", "announcement_date", "pub_date", "date"],
        "closing_date":   ["closing_date"],
        "region":         ["region", "location"],
        "url":            ["url", "link"],
        "pdf_url":        ["pdf_url", "attachment_url"],
    }

    def normalize(self, raw):
        """Map raw fields to the unified schema using FIELD_MAP. Subclasses
        usually only need to extend FIELD_MAP or override completely."""
        out = {"source": self.name, "source_group": self.source_group,
               "record_type": self.record_type}
        for unified_key, candidates in self.FIELD_MAP.items():
            for key in candidates:
                if key in raw and raw[key] not in (None, ""):
                    out[unified_key] = raw[key]
                    break
        return out

    def _make_dedup_hash(self, normalized, raw):
        """Build a stable fingerprint used for deduplication and for the
        permanent 'discarded' list. Subclasses can override, or provide
        `dedup_fields` in the normalized record."""
        fields = normalized.get("dedup_fields")
        if not fields:
            fields = [
                normalized.get("source") or self.name,
                normalized.get("external_id") or normalized.get("url") or normalized.get("title"),
            ]
        blob = "||".join(str(f or "") for f in fields).strip().lower()
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def persist(self, raw_records):
        """Normalize + dedup + persist each raw record to the unified DB.
        Returns (inserted, skipped) counts."""
        inserted = 0
        skipped = 0
        normalized_all = []
        for raw in raw_records or []:
            try:
                norm = self.normalize(raw) or {}
            except Exception as e:
                self.logger.warning(f"normalize() error: {e}")
                continue

            norm.setdefault("source", self.name)
            norm.setdefault("source_group", self.source_group)
            norm.setdefault("record_type", self.record_type)
            norm.setdefault("scraped_at", self.now_iso())
            norm["raw_data"] = raw
            norm["dedup_hash"] = self._make_dedup_hash(norm, raw)
            norm.pop("dedup_fields", None)

            normalized_all.append(norm)
            if db.insert_record(norm):
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped, normalized_all

    def execute(self, run_id=None):
        """Run the scraper end-to-end. Never raises - errors are captured so
        one failing scraper never takes down a scheduled batch."""
        self.stats["start_time"] = self.now_iso()
        self.logger.info(f"=== Starting {self.name} scraper ===")

        raw_results = []
        inserted = 0
        skipped = 0
        error_message = None
        status = "completed"

        try:
            raw_results = self.run() or []
            self.stats["scraped"] = len(raw_results)

            inserted, skipped, normalized = self.persist(raw_results)
            self.stats["new"] = inserted
            self.stats["skipped"] = skipped

            # Keep the daily JSON snapshot for audit / tracking
            if normalized:
                self.save_output(normalized)
        except Exception as e:
            self.logger.exception(f"Unhandled error in {self.name}: {e}")
            self.stats["errors"] += 1
            error_message = str(e)
            status = "error"

        self.stats["end_time"] = self.now_iso()
        self.logger.info(
            f"=== Finished {self.name}: {self.stats['scraped']} found, "
            f"{inserted} new, {skipped} skipped, {self.stats['errors']} errors ==="
        )

        if run_id is not None:
            try:
                db.finish_scraper_run(
                    run_id,
                    status=status if self.stats["errors"] == 0 else "error",
                    items_found=self.stats["scraped"],
                    items_new=inserted,
                    items_skipped=skipped,
                    error_message=error_message,
                )
            except Exception:
                pass

        return raw_results
