import os
import json
import time
import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import config


class BaseScraper:
    """Base class for all scrapers with proxy support, retry, and logging."""

    name = "base"

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
        """Override in subclass. Should return list of dicts."""
        raise NotImplementedError

    def execute(self):
        """Run the scraper with timing and logging."""
        self.stats["start_time"] = self.now_iso()
        self.logger.info(f"=== Starting {self.name} scraper ===")

        try:
            results = self.run()
            self.stats["scraped"] = len(results) if results else 0
            if results:
                self.save_output(results)
        except Exception as e:
            self.logger.exception(f"Unhandled error in {self.name}: {e}")
            self.stats["errors"] += 1
            results = []

        self.stats["end_time"] = self.now_iso()
        self.logger.info(
            f"=== Finished {self.name}: {self.stats['scraped']} items, "
            f"{self.stats['errors']} errors ==="
        )
        return results
