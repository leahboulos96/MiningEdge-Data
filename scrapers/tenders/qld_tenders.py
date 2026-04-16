"""
QLD QTenders scraper.
Source: https://qtenders.hpw.qld.gov.au
Approach: POST to JSON API after obtaining antiforgery cookies.
"""

import re
from scrapers.base_scraper import BaseScraper


class QLDTendersScraper(BaseScraper):
    name = "qld_tenders"
    source_group = "tenders"
    record_type = "tender"

    BASE_URL = "https://qtenders.hpw.qld.gov.au"
    API_URL = "https://qtenders.hpw.qld.gov.au/api/search/tenders"

    def run(self):
        tenders = []
        seen_ids = set()

        # Step 1: GET homepage to obtain antiforgery + affinity cookies
        self.logger.info("Getting QTenders homepage for cookies...")
        resp = self.fetch(self.BASE_URL)
        if not resp:
            self.logger.error("Failed to load QTenders homepage")
            return tenders

        # Extract any antiforgery token from the response
        antiforgery_token = self._extract_antiforgery(resp)
        self.logger.info("Obtained QTenders cookies")

        # Step 2: POST search API for open tenders with pagination
        page = 1
        page_size = 50
        total_pages = None

        while True:
            self.logger.info(f"Fetching QTenders page {page}...")

            search_body = {
                "keywords": "",
                "page": page,
                "pageSize": page_size,
                "sortBy": "Opens",
                "status": "Open",
            }

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "*/*",
                "Origin": self.BASE_URL,
                "Referer": f"{self.BASE_URL}/search?keywords=&page={page}&sortBy=Opens",
            }
            if antiforgery_token:
                headers["RequestVerificationToken"] = antiforgery_token

            resp = self.fetch(
                self.API_URL,
                method="POST",
                json_data=search_body,
                headers=headers,
            )

            if not resp:
                self.logger.error(f"Failed to fetch QTenders page {page}")
                break

            try:
                data = resp.json()
            except Exception:
                self.logger.error(f"Non-JSON response from QTenders API: {resp.text[:200]}")
                break

            # Parse response - try different structures
            items = self._extract_items(data)
            if not items:
                self.logger.info(f"No more items on page {page}")
                break

            if total_pages is None:
                total_pages = self._extract_total_pages(data, page_size)
                self.logger.info(f"Total pages estimated: {total_pages}")

            for item in items:
                tender = self._parse_tender(item)
                tid = tender.get("tender_id_external", "")
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    tenders.append(tender)

            self.logger.info(f"Page {page}: found {len(items)} tenders")

            if total_pages and page >= total_pages:
                break

            page += 1

            if page > 100:
                self.logger.warning("Hit page limit of 100, stopping")
                break

        return tenders

    def _extract_antiforgery(self, resp):
        """Extract antiforgery token from response."""
        # Check for token in HTML
        soup = self.parse_html(resp.text)
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if token_input:
            return token_input.get("value", "")

        # Check meta tag
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta:
            return meta.get("content", "")

        return ""

    def _extract_items(self, data):
        """Extract tender items from API response, handling different structures."""
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # Try common keys
            for key in ["items", "results", "data", "tenders", "records", "value"]:
                if key in data and isinstance(data[key], list):
                    return data[key]

            # If the dict itself looks like a paginated response
            if "totalCount" in data or "total" in data:
                for key in data:
                    if isinstance(data[key], list):
                        return data[key]

        return []

    def _extract_total_pages(self, data, page_size):
        """Extract total page count from response."""
        if isinstance(data, dict):
            total = data.get("totalCount") or data.get("total") or data.get("totalRecords") or 0
            if total:
                return (total + page_size - 1) // page_size
        return None

    def _parse_tender(self, item):
        """Parse a single tender item from the API response."""
        if not isinstance(item, dict):
            return {"tender_id_external": str(item), "source": "qld_tenders", "scraped_at": self.now_iso()}

        # Try various field name patterns
        tender = {
            "tender_id_external": (
                item.get("tenderNumber") or item.get("tenderId") or
                item.get("id") or item.get("referenceNumber") or
                item.get("number") or ""
            ),
            "title": (
                item.get("title") or item.get("tenderTitle") or
                item.get("name") or item.get("description") or ""
            ),
            "description_raw": (
                item.get("description") or item.get("summary") or
                item.get("details") or ""
            ),
            "issuing_entity_name": (
                item.get("agency") or item.get("organisation") or
                item.get("department") or item.get("issuingEntity") or
                item.get("buyer") or ""
            ),
            "published_date": (
                item.get("publishedDate") or item.get("openDate") or
                item.get("publishDate") or item.get("datePublished") or
                item.get("opens") or ""
            ),
            "closing_date": (
                item.get("closingDate") or item.get("closeDate") or
                item.get("dueDate") or item.get("closes") or ""
            ),
            "status": item.get("status") or item.get("tenderStatus") or "Open",
            "region": "QLD",
            "url": self._build_tender_url(item),
            "source": "qld_tenders",
            "scraped_at": self.now_iso(),
        }

        # If title is same as description, clear description
        if tender["title"] == tender["description_raw"]:
            tender["description_raw"] = ""

        return tender

    def _build_tender_url(self, item):
        """Build tender detail URL from item data."""
        tender_id = item.get("id") or item.get("tenderId") or item.get("tenderNumber") or ""
        if tender_id:
            return f"{self.BASE_URL}/tender/{tender_id}"

        url = item.get("url") or item.get("link") or ""
        if url and url.startswith("/"):
            return f"{self.BASE_URL}{url}"

        return self.BASE_URL


if __name__ == "__main__":
    scraper = QLDTendersScraper()
    results = scraper.execute()
    print(f"QLD QTenders: {len(results)} tenders scraped")
