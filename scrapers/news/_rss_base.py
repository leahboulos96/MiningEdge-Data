"""
Shared base for RSS-driven news scrapers. Each concrete news scraper only
has to declare its FEEDS list and (optionally) a `MINING_KEYWORDS` filter.

The default flow:
  1. Fetch each RSS URL (directly; no proxy needed for public RSS feeds)
  2. Parse <item> elements
  3. Filter by mining keywords if configured
  4. Yield one raw dict per article
"""

import re
from datetime import datetime
from scrapers.base_scraper import BaseScraper


MINING_KEYWORDS = [
    "mining", "miner", "lithium", "copper", "gold", "iron ore", "nickel",
    "rare earth", "bauxite", "cobalt", "uranium", "zinc", "coal", "bhp",
    "rio tinto", "fortescue", "resources", "exploration", "drill",
    "tenement", "deposit", "ore body", "commodity", "smelter", "refinery",
]


class RSSNewsScraper(BaseScraper):
    """Base class for news scrapers that consume one or more RSS feeds."""

    source_group = "news"
    record_type = "news"
    FEEDS = []            # list of {"url": ..., "section": ...} dicts
    KEYWORDS = MINING_KEYWORDS
    USE_PROXY = False     # public RSS generally works without proxy
    MINING_ONLY = True    # filter articles by mining keywords

    # news articles map slightly different raw keys
    FIELD_MAP = {
        **BaseScraper.FIELD_MAP,
        "title":          ["title", "headline"],
        "description":    ["summary", "description", "snippet"],
        "entity_name":    ["publisher", "author", "source_name"],
        "published_date": ["published", "pubDate", "date"],
        "url":            ["link", "url"],
    }

    def run(self):
        articles = []
        seen = set()
        for feed in self.FEEDS:
            url = feed["url"]
            self.logger.info(f"Fetching RSS feed: {url}")
            resp = self.fetch(url, use_proxy=self.USE_PROXY)
            if not resp:
                continue
            try:
                soup = self.parse_xml(resp.text)
            except Exception as e:
                self.logger.warning(f"Parse error for {url}: {e}")
                continue

            items = soup.find_all("item") or soup.find_all("entry")
            self.logger.info(f"  -> {len(items)} items in feed")
            for it in items:
                art = self._parse_item(it, feed)
                if not art:
                    continue
                if self.MINING_ONLY and not self._is_mining_related(art):
                    continue
                key = art.get("link") or art.get("title")
                if key in seen:
                    continue
                seen.add(key)
                articles.append(art)
        return articles

    def _parse_item(self, it, feed):
        def t(name):
            el = it.find(name)
            return el.get_text(strip=True) if el else ""

        link = t("link") or (it.find("link").get("href") if it.find("link") and it.find("link").has_attr("href") else "")
        return {
            "title": t("title"),
            "summary": self._clean_html(t("description") or t("summary")),
            "published": t("pubDate") or t("published") or t("updated"),
            "link": link,
            "publisher": feed.get("section") or self.name,
            "scraped_at": self.now_iso(),
            "source_name": self.name,
        }

    def _is_mining_related(self, art):
        text = f"{art.get('title','')} {art.get('summary','')}".lower()
        return any(k in text for k in self.KEYWORDS)

    @staticmethod
    def _clean_html(s):
        return re.sub(r"<[^>]+>", "", s or "").strip()
