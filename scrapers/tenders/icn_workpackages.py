"""
ICN Gateway Work Packages Scraper — gateway.icn.org.au
Scrapes all mining-related Work Packages with full pagination.

Uses the onLoadMoreProjects AJAX handler to paginate through all pages.
Requires authenticated session cookies in icn_cookies.json (same as icn_gateway).
"""

import os
import re
import json
import time
from urllib.parse import unquote

from scrapers.base_scraper import BaseScraper
import config


class ICNWorkpackagesScraper(BaseScraper):
    name = "icn_workpackages"

    BASE_URL = config.ICN_GATEWAY_BASE_URL
    SEARCH_URL = f"{BASE_URL}/projects"
    KEYWORDS = config.ICN_SEARCH_KEYWORDS

    def _load_cookies(self):
        """Load session cookies from JSON file (shared with icn_gateway)."""
        cookie_path = config.ICN_COOKIES_FILE
        if not os.path.exists(cookie_path):
            self.logger.error(
                f"Cookie file not found: {cookie_path}. "
                "Please log in via browser and save cookies to icn_cookies.json."
            )
            return False

        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.error(f"Failed to read cookie file: {e}")
            return False

        required = ["PHPSESSID", "gateway_by_icn_session"]
        missing = [k for k in required if k not in cookies]
        if missing:
            self.logger.error(f"Cookie file missing required cookies: {missing}")
            return False

        for name, value in cookies.items():
            self.session.cookies.set(name, unquote(value), domain="icn.org.au")

        self.logger.info(f"Loaded {len(cookies)} cookies from {cookie_path}")
        return True

    def _save_cookies(self):
        """Save updated cookies back to file so session stays fresh."""
        cookie_path = config.ICN_COOKIES_FILE
        cookies = {}
        for cookie in self.session.cookies:
            cookies[cookie.name] = unquote(cookie.value)
        essential = ["PHPSESSID", "gateway_by_icn_session", "remember_tfa_gateway", "XSRF-TOKEN"]
        saved = {k: v for k, v in cookies.items() if k in essential}
        if saved:
            try:
                with open(cookie_path, "w", encoding="utf-8") as f:
                    json.dump(saved, f, indent=2)
                self.logger.debug(f"Updated cookie file with {len(saved)} cookies")
            except IOError as e:
                self.logger.warning(f"Could not update cookie file: {e}")

    def _get_csrf_token(self):
        """Fetch the projects page and extract the CSRF token."""
        self.logger.info("Fetching CSRF token from projects page...")
        params = (
            f"?show_original_results=1&keywords={self.KEYWORDS}"
            f"&location_select=&location_entry=&location=&location_reserved="
            f"&location_lat=&location_lng=&range=100&view=list&type=workpackage&sort=open"
        )
        resp = self.fetch(f"{self.SEARCH_URL}{params}", use_proxy=False)
        if not resp:
            return None

        if "/login" in resp.url or "login" in resp.text[:500].lower():
            self.logger.error(
                "Session expired — redirected to login page. "
                "Please update icn_cookies.json with fresh cookies."
            )
            return None

        soup = self.parse_html(resp.text)
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            token = meta["content"]
            self.logger.info(f"Got CSRF token: {token[:20]}...")
            return token

        self.logger.error("Could not find CSRF token in page HTML")
        return None

    def _get_xsrf_cookie(self):
        """Get the XSRF-TOKEN cookie value for the X-XSRF-TOKEN header."""
        for cookie in self.session.cookies:
            if cookie.name == "XSRF-TOKEN":
                return cookie.value
        return ""

    def _fetch_page(self, csrf_token, page):
        """Fetch a single page of work package results via AJAX."""
        url = (
            f"{self.SEARCH_URL}?show_original_results=1"
            f"&keywords={self.KEYWORDS}"
            f"&location_select=&location_entry=&location=&location_reserved="
            f"&location_lat=&location_lng=&range=100&view=list"
            f"&type=workpackage&sort=open"
        )

        xsrf_cookie = self._get_xsrf_cookie()

        headers = {
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.BASE_URL,
            "Referer": url,
            "X-AJAX-HANDLER": "onLoadMoreProjects",
            "X-AJAX-FLASH": "1",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf_token,
        }
        if xsrf_cookie:
            headers["X-XSRF-TOKEN"] = xsrf_cookie

        data = (
            f"keywords={self.KEYWORDS}"
            f"&location=&wp_scope=&wp_status=&wp_type="
            f"&open_by=&close_by=&page={page}"
        )

        for attempt in range(1, 4):
            try:
                resp = self.session.post(url, headers=headers, data=data, timeout=60)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (400, 419):
                    self.logger.warning(
                        f"HTTP {resp.status_code} on page {page} (attempt {attempt}/3) — refreshing CSRF"
                    )
                    new_token = self._get_csrf_token()
                    if new_token:
                        csrf_token = new_token
                        headers["X-CSRF-TOKEN"] = csrf_token
                        xsrf_cookie = self._get_xsrf_cookie()
                        if xsrf_cookie:
                            headers["X-XSRF-TOKEN"] = xsrf_cookie
                    time.sleep(2)
                    continue
                self.logger.error(f"AJAX request failed on page {page}: HTTP {resp.status_code}")
                self.stats["errors"] += 1
                return None
            except Exception as e:
                self.logger.warning(f"Request error page {page} (attempt {attempt}/3): {e}")
                time.sleep(2)

        self.logger.error(f"Failed to fetch page {page} after 3 attempts")
        self.stats["errors"] += 1
        return None

    def _extract_items_html(self, resp):
        """Extract the work package cards HTML from the AJAX JSON response."""
        try:
            json_data = resp.json()
        except (ValueError, json.JSONDecodeError):
            if "/login" in resp.text[:500]:
                self.logger.error("Session expired during AJAX call. Please update cookies.")
            else:
                self.logger.error("Invalid JSON response")
            self.stats["errors"] += 1
            return None

        ajax = json_data.get("__ajax", {})
        if not ajax.get("ok"):
            self.logger.error(f"AJAX error: {ajax.get('message', 'unknown')}")
            self.stats["errors"] += 1
            return None

        ops = ajax.get("ops", [])
        for op in ops:
            selector = op.get("selector", "")
            # The load-more response appends cards to the items pane
            if "PaneItems" in selector or "card-tile" in op.get("html", "")[:200]:
                return op.get("html", "")

        return ""

    def _parse_workpackage_card(self, card):
        """Extract data from a single work package card."""
        # Title and ID
        title_tag = card.find("h4", class_="card-title")
        title = ""
        wp_id = ""
        if title_tag:
            link = title_tag.find("a")
            if link:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                id_match = re.search(r"(\d+)", href)
                if id_match:
                    wp_id = id_match.group(1)

        # Project name
        project_tag = card.find("h5", class_="subtitle-bolder")
        project_name = project_tag.get_text(strip=True) if project_tag else ""

        # Company
        company_tag = card.find("h5", class_="subtitle-upper")
        company = company_tag.get_text(strip=True) if company_tag else ""

        # Description
        desc_tag = card.find("p", class_="card-text")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Status
        status = ""
        status_tag = card.find("span", class_="status-badge")
        if status_tag:
            status = status_tag.get_text(strip=True)

        # Scope
        scope = ""
        scope_section = card.find("div", class_="card-scope-section")
        if scope_section:
            scope_spans = scope_section.find_all("span", class_="scope")
            scopes = []
            for s in scope_spans:
                text_span = s.find_all("span")
                for ts in text_span:
                    if "scope-icon" not in ts.get("class", []):
                        text = ts.get_text(strip=True)
                        if text:
                            scopes.append(text)
            scope = " / ".join(scopes) if scopes else ""

        # Work package type from card class
        wp_type = "standard"
        card_inner = card.find("div", class_="card")
        if card_inner:
            classes = card_inner.get("class", [])
            for cls in classes:
                if cls.startswith("wp-type-"):
                    wp_type = cls.replace("wp-type-", "")

        # PDF URL
        pdf_url = ""
        doc_link = card.find("a", class_="card-icon-link")
        if doc_link:
            pdf_url = doc_link.get("href", "").replace("&amp;", "&")

        # Date fields and location
        eoi_open = ""
        eoi_close = ""
        location = ""

        dl = card.find("dl")
        if dl:
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt_tag, dd_tag in zip(dts, dds):
                label = dt_tag.get_text(strip=True).lower()
                value = dd_tag.get_text(strip=True)
                if "open" in label:
                    eoi_open = value
                elif "close" in label:
                    eoi_close = value
                elif "location" in label:
                    location = value

        return {
            "tender_id_external": wp_id,
            "title": title,
            "description_raw": description,
            "issuing_entity_name": company,
            "project_name": project_name,
            "published_date": eoi_open,
            "closing_date": eoi_close,
            "status": status,
            "region": location,
            "url": f"{self.BASE_URL}/projects/{wp_id}" if wp_id else "",
            "pdf_url": pdf_url,
            "type": "workpackage",
            "scope": scope,
            "wp_type": wp_type,
            "source": self.name,
            "scraped_at": self.now_iso(),
        }

    def _parse_cards(self, html):
        """Parse all work package cards from an HTML fragment."""
        soup = self.parse_html(html)
        cards = soup.find_all("div", class_="card-tile")
        results = []
        for card in cards:
            try:
                result = self._parse_workpackage_card(card)
                if result and result.get("title"):
                    results.append(result)
            except Exception as e:
                self.logger.warning(f"Error parsing work package card: {e}")
                self.stats["errors"] += 1
        return results

    def run(self):
        """Main entry point — paginate through all work package pages."""
        # Step 1: Load cookies
        if not self._load_cookies():
            return []

        # Step 2: Get CSRF token (also loads page 1 results implicitly)
        csrf_token = self._get_csrf_token()
        if not csrf_token:
            return []

        all_results = []
        max_pages = 50  # Safety limit

        # Step 3: Fetch page 1 via the initial search
        self.logger.info("Fetching page 1 of work packages...")
        resp = self._fetch_page(csrf_token, page=1)
        if resp:
            html = self._extract_items_html(resp)
            if html and html.strip():
                items = self._parse_cards(html)
                self.logger.info(f"Page 1: {len(items)} work packages")
                all_results.extend(items)
            else:
                self.logger.info("Page 1 returned no items")

        # Step 4: Paginate through remaining pages
        page = 2
        while page <= max_pages:
            time.sleep(1)  # Be polite
            self.logger.info(f"Fetching page {page} of work packages...")

            resp = self._fetch_page(csrf_token, page=page)
            if not resp:
                break

            html = self._extract_items_html(resp)
            if not html or not html.strip():
                self.logger.info(f"Page {page} returned no items — reached end of results")
                break

            items = self._parse_cards(html)
            if not items:
                self.logger.info(f"Page {page} had no parseable cards — reached end of results")
                break

            self.logger.info(f"Page {page}: {len(items)} work packages")
            all_results.extend(items)
            page += 1

        # Step 5: Save updated cookies
        self._save_cookies()

        # Step 6: Deduplicate
        seen = set()
        unique = []
        for item in all_results:
            key = (item.get("tender_id_external", ""), item.get("title", ""))
            if key not in seen:
                seen.add(key)
                unique.append(item)

        self.logger.info(
            f"Total: {len(unique)} unique work packages across {page - 1} pages "
            f"({len(all_results) - len(unique)} duplicates removed)"
        )
        return unique
