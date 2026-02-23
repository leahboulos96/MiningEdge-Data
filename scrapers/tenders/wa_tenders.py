"""
WA Tenders & Contracts scraper.
Source: https://www.tenders.wa.gov.au
Approach: Session-based scraping with CSRF token, POST search for open tenders.
"""

import re
from urllib.parse import urljoin
from scrapers.base_scraper import BaseScraper


class WATendersScraper(BaseScraper):
    name = "wa_tenders"

    BASE_URL = "https://www.tenders.wa.gov.au/watenders"
    SEARCH_URL = "https://www.tenders.wa.gov.au/watenders/tender/search/tender-search.action"

    def run(self):
        tenders = []
        seen_ids = set()

        # Step 1: GET search page to obtain CSRF token and session cookie
        self.logger.info("Getting WA Tenders search page for session/CSRF...")
        init_url = f"{self.SEARCH_URL}?action=search-from-main-page"
        resp = self.fetch(init_url)
        if not resp:
            self.logger.error("Failed to load WA Tenders search page")
            return tenders

        soup = self.parse_html(resp.text)
        csrf_token = self._extract_csrf(soup, resp.text)
        if not csrf_token:
            self.logger.error("Could not extract CSRF token from WA Tenders")
            return tenders
        self.logger.info(f"Got CSRF token: {csrf_token[:20]}...")

        # Step 2: POST search for open tenders
        page = 1
        while True:
            self.logger.info(f"Fetching WA Tenders page {page}...")
            search_url = f"{self.SEARCH_URL}?CSRFNONCE={csrf_token}&noreset=yes&action=do-advanced-tender-search"

            form_data = {
                "action": "do-advanced-tender-search",
                "actionType": "$f.actionType",
                "changeLevel": "",
                "inputlist": "hasETB",
                "saveSearchProfileName": "",
                "withdrawalReason": "",
                "expiredReason": "",
                "tenderState": "",
                "tenderId": "",
                "bySupplierId": "-1",
                "viaSearchButton": "true",
                "ageRestriction": "",
                "state": "Open",
                "type": "Any",
                "workType": "any",
                "keywords": "",
                "anyWord": "exactMatch",
                "tenderCode": "",
                "tenderTitle": "",
                "publicAuthorityId": "-1",
                "issuingBusinessId": "-1",
                "supplierBusinessName": "",
                "regionId": "-1",
                "unspscCode1": "",
                "unspscCode2": "",
                "unspscCode3": "",
                "openingDateFromString": "",
                "openingDateToString": "",
                "closingDateFromString": "",
                "closingDateToString": "",
                "awardDateFromString": "",
                "awardDateToString": "",
            }

            resp = self.fetch(search_url, method="POST", data=form_data)
            if not resp:
                self.logger.error(f"Failed to fetch WA Tenders search results page {page}")
                break

            soup = self.parse_html(resp.text)
            page_tenders = self._parse_results(soup)

            if not page_tenders:
                self.logger.info(f"No more tenders found on page {page}")
                break

            for t in page_tenders:
                tid = t.get("tender_id_external", "")
                if tid and tid not in seen_ids:
                    seen_ids.add(tid)
                    tenders.append(t)

            self.logger.info(f"Page {page}: found {len(page_tenders)} tenders")

            # Check for next page link
            next_link = self._find_next_page(soup)
            if not next_link:
                break

            # Update the search URL for next page
            csrf_token = self._extract_csrf(soup, resp.text) or csrf_token
            page += 1

            # Safety limit
            if page > 50:
                self.logger.warning("Hit page limit of 50, stopping")
                break

        return tenders

    def _extract_csrf(self, soup, html_text):
        """Extract CSRFNONCE from HTML."""
        # Look in hidden input fields
        csrf_input = soup.find("input", {"name": "CSRFNONCE"})
        if csrf_input:
            return csrf_input.get("value", "")

        # Look in URLs on the page
        match = re.search(r"CSRFNONCE=([A-F0-9]+)", html_text)
        if match:
            return match.group(1)

        return ""

    def _parse_results(self, soup):
        """Parse tender listing results from HTML."""
        tenders = []

        # First detect table header columns to map indices
        col_map = self._detect_columns(soup)

        # WA Tenders uses tables for listing
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            # Find the tender detail link - must contain id= parameter
            link = row.find("a", href=re.compile(r"display-tender-details.*id=\d+|id=\d+.*display-tender-details"))
            if not link:
                link = row.find("a", href=re.compile(r"tender-details\.action\?id=\d+"))
            if not link:
                continue

            href = link.get("href", "")
            link_text = link.get_text(strip=True)

            # Extract tender ID from URL: id=67609
            tender_id = ""
            id_match = re.search(r"[?&]id=(\d+)", href)
            if not id_match:
                continue
            tender_id = id_match.group(1)

            full_url = urljoin("https://www.tenders.wa.gov.au", href)
            cell_texts = [c.get_text(strip=True) for c in cells]

            tender = {
                "tender_id_external": tender_id,
                "title": link_text or "",
                "description_raw": "",
                "issuing_entity_name": "",
                "published_date": "",
                "closing_date": "",
                "status": "Open",
                "region": "WA",
                "url": full_url,
                "source": "wa_tenders",
                "scraped_at": self.now_iso(),
            }

            # Map cells using detected column order
            if col_map:
                for field, idx in col_map.items():
                    if idx < len(cell_texts):
                        tender[field] = cell_texts[idx]
                # Ensure title is from the link text if available
                if link_text:
                    tender["title"] = link_text
            else:
                # Fallback: smart assignment based on content
                for i, text in enumerate(cell_texts):
                    if not text:
                        continue
                    if self._looks_like_date(text):
                        if not tender["closing_date"]:
                            tender["closing_date"] = text
                        elif not tender["published_date"]:
                            tender["published_date"] = text
                    elif self._looks_like_entity(text) and not tender["issuing_entity_name"]:
                        tender["issuing_entity_name"] = text

            # Use link text as title if not set
            if not tender["title"] and link_text:
                tender["title"] = link_text

            # Generate a unique ID if we couldn't extract one
            if not tender["tender_id_external"]:
                tender["tender_id_external"] = tender["title"][:80]

            tenders.append(tender)

        # Fallback: look for div-based listings
        if not tenders:
            tenders = self._parse_div_results(soup)

        return tenders

    def _detect_columns(self, soup):
        """Detect table column order from header row."""
        col_map = {}
        header_row = soup.find("tr")
        if not header_row:
            return col_map

        headers = header_row.find_all(["th", "td"])
        field_patterns = {
            "tender_id_external": ["request", "tender no", "reference", "code", "number", "id"],
            "title": ["title", "name", "subject", "description"],
            "issuing_entity_name": ["agency", "authority", "organisation", "department", "issued by"],
            "closing_date": ["clos", "deadline", "due"],
            "published_date": ["open", "publish", "release", "advertis"],
            "status": ["status", "state"],
        }

        for i, th in enumerate(headers):
            th_text = th.get_text(strip=True).lower()
            for field, patterns in field_patterns.items():
                if any(p in th_text for p in patterns):
                    col_map[field] = i
                    break

        return col_map

    def _looks_like_entity(self, text):
        """Check if text looks like a government entity name."""
        keywords = ["department", "government", "agency", "council", "authority",
                     "commission", "board", "wa ", "western", "minister", "office"]
        return any(kw in text.lower() for kw in keywords)

    def _parse_div_results(self, soup):
        """Fallback parser for div-based tender listings."""
        tenders = []
        # Look for content blocks that contain tender info
        for block in soup.find_all(["div", "article", "section"], class_=True):
            classes = " ".join(block.get("class", []))
            if "tender" in classes.lower() or "result" in classes.lower() or "listing" in classes.lower():
                link = block.find("a")
                if not link:
                    continue

                href = link.get("href", "")
                title = link.get_text(strip=True)

                tender = {
                    "tender_id_external": "",
                    "title": title,
                    "description_raw": block.get_text(" ", strip=True)[:500],
                    "issuing_entity_name": "",
                    "published_date": "",
                    "closing_date": "",
                    "status": "Open",
                    "region": "WA",
                    "url": urljoin("https://www.tenders.wa.gov.au", href),
                    "source": "wa_tenders",
                    "scraped_at": self.now_iso(),
                }

                # Extract tender code from title or text
                code_match = re.search(r"\b([A-Z]{2,}\d{3,}[A-Z0-9]*)\b", title)
                if code_match:
                    tender["tender_id_external"] = code_match.group(1)
                else:
                    tender["tender_id_external"] = title[:50]

                tenders.append(tender)

        return tenders

    def _find_next_page(self, soup):
        """Find next page link in pagination."""
        # Look for "Next" or ">" links
        for link in soup.find_all("a"):
            text = link.get_text(strip=True).lower()
            if text in ("next", ">", ">>", "next page", "next >"):
                return link.get("href", "")
        return ""

    def _looks_like_date(self, text):
        """Check if text looks like a date string."""
        return bool(re.search(r"\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}", text) or
                     re.search(r"\d{1,2}\s+\w+\s+\d{4}", text))


if __name__ == "__main__":
    scraper = WATendersScraper()
    results = scraper.execute()
    print(f"WA Tenders: {len(results)} tenders scraped")
