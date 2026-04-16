"""
ASX Company Announcements scraper.
Source: https://www.asx.com.au (via markitdigital API)
Approach: Direct JSON API calls, no proxy needed.
"""

import time
import config
from scrapers.base_scraper import BaseScraper


class ASXScraper(BaseScraper):
    name = "asx_announcements"
    source_group = "asx"
    record_type = "announcement"

    ANNOUNCEMENTS_URL = f"{config.ASX_API_BASE}/companies/{{ticker}}/announcements"
    HEADER_URL = f"{config.ASX_API_BASE}/companies/{{ticker}}/header"

    def _pdf_url(self, doc_key):
        """Build PDF URL using current config token."""
        return f"{config.ASX_CDN_BASE}/file/{doc_key}?access_token={config.ASX_ACCESS_TOKEN}"

    def run(self):
        announcements = []
        seen_keys = set()
        tickers = config.ASX_TICKERS
        total = len(tickers)

        self.logger.info(f"Starting ASX scraper for {total} tickers")

        for i, ticker in enumerate(tickers, 1):
            ticker = ticker.strip().upper()
            if not ticker:
                continue

            self.logger.info(f"[{i}/{total}] Scraping {ticker}...")

            try:
                ticker_announcements = self._scrape_ticker(ticker, seen_keys)
                announcements.extend(ticker_announcements)
                self.logger.debug(f"  {ticker}: {len(ticker_announcements)} announcements")
            except Exception as e:
                self.logger.error(f"  {ticker}: Error - {e}")
                self.stats["errors"] += 1

            # Rate limiting
            if i < total:
                time.sleep(config.ASX_RATE_LIMIT_DELAY)

        return announcements

    def _scrape_ticker(self, ticker, seen_keys):
        """Scrape announcements for a single ticker."""
        results = []

        # Fetch announcements first (the main data we need)
        url = self.ANNOUNCEMENTS_URL.format(ticker=ticker)
        url += f"?count={config.ASX_ANNOUNCEMENTS_COUNT}"

        resp = self.fetch(url, use_proxy=False)
        if not resp:
            return results

        try:
            data = resp.json()
        except Exception:
            self.logger.warning(f"Non-JSON response for {ticker}")
            return results

        # Handle different response structures
        outer = data.get("data", data)
        items = outer.get("items", [])

        if not items:
            self.logger.debug(f"No announcements for {ticker}")
            return results

        # Use displayName from announcements response, fallback to header API
        display_name = outer.get("displayName", "")
        if not display_name:
            display_name = self._get_company_name(ticker)

        for item in items:
            doc_key = item.get("documentKey", "")

            # Deduplicate by document key
            if doc_key in seen_keys:
                continue
            seen_keys.add(doc_key)

            # Build PDF URL
            pdf_url = ""
            if doc_key:
                pdf_url = self._pdf_url(doc_key)

            # Build announcement page URL
            ann_url = f"https://www.asx.com.au/announcements/pdf/{doc_key}" if doc_key else ""

            announcement = {
                "ticker": ticker,
                "company_name_raw": display_name,
                "announcement_title": item.get("headline", ""),
                "announcement_date": item.get("date", ""),
                "announcement_type": item.get("announcementType", ""),
                "url": ann_url,
                "pdf_url": pdf_url,
                "is_price_sensitive": item.get("isPriceSensitive", False),
                "file_size": item.get("fileSize", ""),
                "snippet_raw": "",
                "scraped_at": self.now_iso(),
            }

            results.append(announcement)

        return results

    def _get_company_name(self, ticker):
        """Fetch company display name from header API."""
        url = self.HEADER_URL.format(ticker=ticker)
        resp = self.fetch(url, use_proxy=False)
        if not resp:
            return ticker

        try:
            data = resp.json()
            return data.get("data", {}).get("displayName", ticker)
        except Exception:
            return ticker


if __name__ == "__main__":
    scraper = ASXScraper()
    results = scraper.execute()
    print(f"ASX: {len(results)} announcements scraped")
