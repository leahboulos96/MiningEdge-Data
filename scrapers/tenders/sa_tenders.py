"""
SA Tenders & Contracts scraper.
Source: https://www.tenders.sa.gov.au
Approach: Fetch search results page, parse HTML listing, then optionally detail pages.
"""

import re
from urllib.parse import urljoin
from scrapers.base_scraper import BaseScraper


class SATendersScraper(BaseScraper):
    name = "sa_tenders"

    BASE_URL = "https://www.tenders.sa.gov.au"
    SEARCH_URL = "https://www.tenders.sa.gov.au/tender/search"
    MAX_PAGES = 20  # Safety limit - covers ~300 tenders per run

    def run(self):
        tenders = []
        seen_ids = set()

        page = 1
        while True:
            self.logger.info(f"Fetching SA Tenders page {page}...")

            search_params = (
                f"?keywords=&tenderCode=&tenderState=OPEN&tenderType="
                f"&issuingBusinessId=&awardedSupplier.id=&awardedSupplier.name="
                f"&openThisWeek=false&openingDateFrom=&openingDateTo="
                f"&closeThisWeek=false&closingDateFrom=&closingDateTo="
                f"&groupBy=NONE&page={page}&searchTitle="
            )
            url = self.SEARCH_URL + search_params
            resp = self.fetch(url)

            if not resp:
                self.logger.error(f"Failed to fetch SA Tenders page {page}")
                break

            soup = self.parse_html(resp.text)
            page_tenders = self._parse_search_results(soup)

            if not page_tenders:
                self.logger.info(f"No more tenders on page {page}")
                break

            for tender_summary in page_tenders:
                tid = tender_summary.get("tender_id_external", "")
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
                tenders.append(tender_summary)

            self.logger.info(f"Page {page}: found {len(page_tenders)} tenders (total: {len(tenders)})")

            if not self._has_next_page(soup, page):
                break

            page += 1
            if page > self.MAX_PAGES:
                self.logger.info(f"Reached page limit ({self.MAX_PAGES}), stopping")
                break

        # Optionally fetch detail pages for the first batch (most recent)
        # Limit to avoid excessive requests
        detail_limit = min(50, len(tenders))
        if detail_limit > 0:
            self.logger.info(f"Fetching details for {detail_limit} tenders...")
            for i, tender in enumerate(tenders[:detail_limit]):
                detail_url = tender.get("url", "")
                if detail_url:
                    detail = self._scrape_detail(detail_url)
                    if detail:
                        tender.update(detail)
                if (i + 1) % 10 == 0:
                    self.logger.info(f"  Detail pages: {i + 1}/{detail_limit}")

        return tenders

    def _parse_search_results(self, soup):
        """Parse tender listings from search results HTML."""
        tenders = []

        # SA Tenders uses table-based layout for results
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            link = row.find("a", href=True)
            if not link:
                continue

            href = link.get("href", "")
            if "/tender/view" not in href:
                continue

            tender_code = ""
            title = ""
            detail_url = urljoin(self.BASE_URL, href)
            cell_texts = [c.get_text(strip=True) for c in cells]

            # Get link text as title
            title = link.get_text(strip=True) or ""

            # First cell often contains tender code + status
            if cell_texts:
                raw_code = cell_texts[0]
                # Strip status suffixes (Open, Closed, Cancelled, etc.)
                tender_code = re.sub(r'(Open|Closed|Cancelled|Awarded|Future|Expired)\s*$', '', raw_code).strip()
            else:
                tender_code = ""

            tender_id_match = re.search(r"id=(\d+)", href)
            if not tender_code and tender_id_match:
                tender_code = tender_id_match.group(1)

            # Parse issuing entity from the concatenated text
            issuing_entity = ""
            closing_date = ""
            for cell in cells:
                cell_text = cell.get_text(" ", strip=True)
                # Look for "Issued by: XXX" pattern
                issued_match = re.search(r"Issued by:\s*(.+?)(?:Category:|$)", cell_text)
                if issued_match:
                    issuing_entity = issued_match.group(1).strip()
                # Look for date patterns
                date_match = re.search(r"(\d{1,2}[\s/\-]\w{3,9}[\s/\-]\d{2,4})", cell_text)
                if date_match and not closing_date:
                    closing_date = date_match.group(1)

            tender = {
                "tender_id_external": tender_code,
                "title": title,
                "description_raw": "",
                "issuing_entity_name": issuing_entity,
                "published_date": "",
                "closing_date": closing_date,
                "status": "Open",
                "region": "SA",
                "url": detail_url,
                "source": "sa_tenders",
                "scraped_at": self.now_iso(),
            }

            if tender_code or title:
                tenders.append(tender)

        # Fallback: look for div-based results with links to tender/view
        if not tenders:
            tenders = self._parse_link_results(soup)

        return tenders

    def _parse_link_results(self, soup):
        """Fallback parser that finds all tender detail links."""
        tenders = []
        seen_hrefs = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/tender/view?id=" not in href:
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            detail_url = urljoin(self.BASE_URL, href)
            tender_id_match = re.search(r"id=(\d+)", href)
            tender_code = tender_id_match.group(1) if tender_id_match else ""

            parent = link.find_parent(["tr", "div", "li", "article"])
            parent_text = parent.get_text(" ", strip=True) if parent else ""

            tender = {
                "tender_id_external": tender_code,
                "title": title,
                "description_raw": "",
                "issuing_entity_name": "",
                "published_date": "",
                "closing_date": "",
                "status": "Open",
                "region": "SA",
                "url": detail_url,
                "source": "sa_tenders",
                "scraped_at": self.now_iso(),
            }

            date_matches = re.findall(r"\d{1,2}[\s/\-]\w{3,9}[\s/\-]\d{2,4}", parent_text)
            if date_matches:
                tender["closing_date"] = date_matches[-1]

            tenders.append(tender)

        return tenders

    def _scrape_detail(self, url):
        """Scrape a single SA Tender detail page."""
        resp = self.fetch(url)
        if not resp:
            return None

        soup = self.parse_html(resp.text)
        detail = {}

        field_map = {
            "issuing_entity_name": ["Issued By", "Issuing Business", "Organisation", "Agency"],
            "closing_date": ["Closing Date", "Close Date", "Closes"],
            "published_date": ["Published", "Opening Date", "Open Date", "Opened"],
            "description_raw": ["Description", "Tender Description", "Details"],
            "status": ["Status", "Tender Status", "State"],
            "category": ["Category", "UNSPSC", "Categories"],
        }

        for field_name, labels in field_map.items():
            value = self._extract_field(soup, labels)
            if value:
                detail[field_name] = value

        code_value = self._extract_field(soup, ["Tender Code", "Reference", "Tender Number", "Code"])
        if code_value:
            detail["tender_id_external"] = code_value

        return detail

    def _extract_field(self, soup, labels):
        """Extract field by searching for label-value patterns."""
        for label_tag in soup.find_all(["dt", "th", "label", "strong", "b", "span"]):
            tag_text = label_tag.get_text(strip=True).rstrip(":")
            for label in labels:
                if label.lower() in tag_text.lower() and len(tag_text) < len(label) + 15:
                    nxt = label_tag.find_next_sibling(["dd", "td", "span", "div", "p"])
                    if nxt:
                        value = nxt.get_text(strip=True)
                        if value and len(value) < 500:
                            return value
                    parent = label_tag.parent
                    if parent:
                        nxt = parent.find_next_sibling()
                        if nxt:
                            value = nxt.get_text(strip=True)
                            if value and len(value) < 500:
                                return value
        return ""

    def _has_next_page(self, soup, current_page):
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            href = link.get("href", "")
            if text in ("next", ">", ">>", "next page"):
                return True
            if f"page={current_page + 1}" in href:
                return True
        return False

    def _looks_like_date(self, text):
        return bool(re.search(r"\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}", text) or
                     re.search(r"\d{1,2}\s+\w{3,9}\s+\d{4}", text))

    def _looks_like_entity(self, text):
        keywords = ["department", "government", "agency", "council", "authority",
                     "commission", "board", "procurement", "sa "]
        return any(kw in text.lower() for kw in keywords)


if __name__ == "__main__":
    scraper = SATendersScraper()
    results = scraper.execute()
    print(f"SA Tenders: {len(results)} tenders scraped")
