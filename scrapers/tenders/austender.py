"""
AusTender (Commonwealth Government) scraper.
Source: https://www.tenders.gov.au
Approach: Parse RSS feed for listing, then scrape detail pages for full fields.
"""

import re
from scrapers.base_scraper import BaseScraper


class AusTenderScraper(BaseScraper):
    name = "austender"
    source_group = "tenders"
    record_type = "tender"

    RSS_URL = "https://www.tenders.gov.au/public_data/rss/rss.xml"
    BASE_URL = "https://www.tenders.gov.au"

    def run(self):
        tenders = []
        seen_ids = set()

        # Step 1: Fetch RSS feed
        self.logger.info("Fetching AusTender RSS feed...")
        resp = self.fetch(self.RSS_URL)
        if not resp:
            self.logger.error("Failed to fetch RSS feed")
            return tenders

        soup = self.parse_xml(resp.text)
        items = soup.find_all("item")
        self.logger.info(f"Found {len(items)} items in RSS feed")

        # Step 2: Parse each RSS item
        for item in items:
            title_text = item.find("title").get_text(strip=True) if item.find("title") else ""
            link = item.find("link").get_text(strip=True) if item.find("link") else ""
            description = item.find("description").get_text(strip=True) if item.find("description") else ""
            pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""

            # Extract ATM ID from title (format: "ATM_ID: description text")
            atm_id = ""
            if ":" in title_text:
                atm_id = title_text.split(":")[0].strip()

            if atm_id in seen_ids:
                continue
            seen_ids.add(atm_id)

            tender = {
                "tender_id_external": atm_id,
                "title": title_text,
                "description_raw": description,
                "issuing_entity_name": "",
                "published_date": pub_date,
                "closing_date": "",
                "status": "Open",
                "region": "",
                "url": link,
                "source": "austender",
                "scraped_at": self.now_iso(),
            }

            # Step 3: Fetch detail page for additional fields
            if link:
                detail = self._scrape_detail(link)
                if detail:
                    tender.update(detail)

            tenders.append(tender)
            self.logger.debug(f"Scraped: {atm_id} - {title_text[:60]}")

        return tenders

    def _scrape_detail(self, url):
        """Scrape a single AusTender detail page for extra fields."""
        resp = self.fetch(url)
        if not resp:
            return None

        soup = self.parse_html(resp.text)
        detail = {}

        # AusTender detail pages use definition list or table-like key-value pairs
        # Look for common patterns
        text = soup.get_text(" ", strip=True)

        # Try to extract fields from page text using label patterns
        detail["issuing_entity_name"] = self._extract_field(soup, text, [
            "Agency", "Organisation", "Entity", "Department"
        ])
        detail["closing_date"] = self._extract_field(soup, text, [
            "Close Date", "Closing Date", "Close Date & Time", "Closes"
        ])
        detail["region"] = self._extract_field(soup, text, [
            "Location", "State", "Address"
        ])

        # Try to get category
        category = self._extract_field(soup, text, ["Category", "UNSPSC"])
        if category:
            detail["category"] = category

        # Try to get a richer description from the detail page
        desc_section = self._extract_field(soup, text, [
            "Description", "Opportunity Description", "ATM Description"
        ])
        if desc_section and len(desc_section) > len(detail.get("description_raw", "")):
            detail["description_raw"] = desc_section

        return detail

    def _extract_field(self, soup, full_text, labels):
        """Try to extract a field value by looking for label patterns in the HTML."""
        # Strategy 1: Look for dt/dd pairs (most reliable on gov sites)
        for dt in soup.find_all(["dt", "th", "label", "strong", "b"]):
            dt_text = dt.get_text(strip=True).rstrip(":")
            for label in labels:
                if label.lower() == dt_text.lower() or (
                    label.lower() in dt_text.lower() and len(dt_text) < len(label) + 15
                ):
                    nxt = dt.find_next_sibling(["dd", "td", "span", "div", "p"])
                    if nxt:
                        value = nxt.get_text(strip=True)
                        if value and len(value) < 500 and not self._is_junk(value):
                            return value
                    parent = dt.parent
                    if parent:
                        nxt = parent.find_next_sibling()
                        if nxt:
                            value = nxt.get_text(strip=True)
                            if value and len(value) < 500 and not self._is_junk(value):
                                return value

        # Strategy 2: Regex on full text
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:\-]\s*(.+?)(?:\n|$)", re.IGNORECASE)
            match = pattern.search(full_text)
            if match:
                value = match.group(1).strip()
                if value and len(value) < 500 and not self._is_junk(value):
                    return value

        return ""

    def _is_junk(self, value):
        """Check if extracted value looks like junk (navigation, form elements, etc.)."""
        junk_patterns = [
            "password", "login", "register", "forgot", "sign in", "sign up",
            "javascript:", "click here", "submit", "search",
        ]
        lower = value.lower()
        return any(p in lower for p in junk_patterns) or len(value) < 2


if __name__ == "__main__":
    scraper = AusTenderScraper()
    results = scraper.execute()
    print(f"AusTender: {len(results)} tenders scraped")
