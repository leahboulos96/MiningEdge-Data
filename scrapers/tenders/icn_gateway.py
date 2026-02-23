"""
ICN Gateway Scraper — gateway.icn.org.au
Scrapes mining-related Projects and Work Packages from ICN Gateway.

Requires authenticated session cookies in icn_cookies.json.
You must log in via browser (2FA required), then export your cookies.
"""

import os
import re
import json
import time
from urllib.parse import unquote

from scrapers.base_scraper import BaseScraper
import config


class ICNGatewayScraper(BaseScraper):
    name = "icn_gateway"

    BASE_URL = config.ICN_GATEWAY_BASE_URL
    SEARCH_URL = f"{BASE_URL}/projects"
    KEYWORDS = config.ICN_SEARCH_KEYWORDS

    # Types to scrape: both projects and work packages
    SEARCH_TYPES = ["workpackage", "project"]

    def _load_cookies(self):
        """Load session cookies from JSON file."""
        cookie_path = config.ICN_COOKIES_FILE
        if not os.path.exists(cookie_path):
            self.logger.error(
                f"Cookie file not found: {cookie_path}. "
                "Please log in via browser and save cookies to icn_cookies.json. "
                "See README for instructions."
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
            self.logger.error(
                f"Cookie file missing required cookies: {missing}. "
                "Please re-export cookies after logging in."
            )
            return False

        # Set cookies on session (URL-decode in case of %3D artifacts)
        for name, value in cookies.items():
            self.session.cookies.set(name, unquote(value), domain="icn.org.au")

        self.logger.info(f"Loaded {len(cookies)} cookies from {cookie_path}")
        return True

    def _save_cookies(self):
        """Save updated cookies back to file so session stays fresh."""
        cookie_path = config.ICN_COOKIES_FILE
        cookies = {}
        for cookie in self.session.cookies:
            # URL-decode values to avoid %3D artifacts
            cookies[cookie.name] = unquote(cookie.value)
        # Only save the essential session cookies (not analytics)
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
        resp = self.fetch(
            f"{self.SEARCH_URL}?keywords={self.KEYWORDS}&type=workpackage&sort=open&view=list&range=100",
            use_proxy=False,
        )
        if not resp:
            return None

        # Check if we got redirected to login
        if "/login" in resp.url or "login" in resp.text[:500].lower():
            self.logger.error(
                "Session expired — redirected to login page. "
                "Please update icn_cookies.json with fresh cookies from your browser."
            )
            return None

        # Extract CSRF token from meta tag
        soup = self.parse_html(resp.text)
        meta = soup.find("meta", {"name": "csrf-token"})
        if meta and meta.get("content"):
            token = meta["content"]
            self.logger.info(f"Got CSRF token: {token[:20]}...")
            return token

        self.logger.error("Could not find CSRF token in page HTML")
        return None

    def _fetch_search_results(self, csrf_token, search_type):
        """Fetch search results via AJAX for a given type (project/workpackage)."""
        self.logger.info(f"Fetching {search_type} results...")

        url = (
            f"{self.SEARCH_URL}?show_original_results=1"
            f"&keywords={self.KEYWORDS}&range=100&view=list"
            f"&type={search_type}&sort=open"
        )

        headers = {
            "X-AJAX-HANDLER": "onSearchItemProjects",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-TOKEN": csrf_token,
        }

        data = (
            f"_token={csrf_token}"
            f"&keywords={self.KEYWORDS}"
            f"&location=&range=100&view=list"
            f"&type={search_type}&sort=open"
        )

        # Retry up to 3 times with CSRF refresh on 400/419
        resp = None
        for attempt in range(1, 4):
            try:
                resp = self.session.post(url, headers=headers, data=data, timeout=60)
                if resp.status_code == 200:
                    break
                if resp.status_code in (400, 419):
                    self.logger.warning(
                        f"HTTP {resp.status_code} for {search_type} (attempt {attempt}/3) — refreshing CSRF token"
                    )
                    # Re-fetch CSRF token (session may have rotated)
                    new_token = self._get_csrf_token()
                    if new_token:
                        csrf_token = new_token
                        headers["X-CSRF-TOKEN"] = csrf_token
                        data = (
                            f"_token={csrf_token}"
                            f"&keywords={self.KEYWORDS}"
                            f"&location=&range=100&view=list"
                            f"&type={search_type}&sort=open"
                        )
                    time.sleep(2)
                    continue
                self.logger.error(f"AJAX request failed for {search_type}: HTTP {resp.status_code}")
                self.stats["errors"] += 1
                return None
            except Exception as e:
                self.logger.warning(f"Request error for {search_type} (attempt {attempt}/3): {e}")
                time.sleep(2)

        if not resp or resp.status_code != 200:
            self.logger.error(f"AJAX request failed for {search_type} after 3 attempts")
            self.stats["errors"] += 1
            return None

        try:
            json_data = resp.json()
        except (ValueError, json.JSONDecodeError):
            # Check if redirected to login
            if "/login" in resp.text[:500]:
                self.logger.error(
                    "Session expired during AJAX call. "
                    "Please update icn_cookies.json with fresh cookies."
                )
            else:
                self.logger.error(f"Invalid JSON response for {search_type}")
            self.stats["errors"] += 1
            return None

        # Validate response structure
        ajax = json_data.get("__ajax", {})
        if not ajax.get("ok"):
            self.logger.error(f"AJAX error: {ajax.get('message', 'unknown')}")
            self.stats["errors"] += 1
            return None

        # Find the HTML patch for items
        ops = ajax.get("ops", [])
        items_html = None
        for op in ops:
            selector = op.get("selector", "")
            if "PaneItems" in selector:
                items_html = op.get("html", "")
                break

        if items_html is None:
            self.logger.warning(f"No items HTML found in AJAX response for {search_type}")
            return ""

        return items_html

    def _parse_workpackage_cards(self, html):
        """Parse work package cards from HTML."""
        soup = self.parse_html(html)
        cards = soup.find_all("div", class_="card-tile")
        results = []

        for card in cards:
            try:
                result = self._parse_one_workpackage(card)
                if result and result.get("title"):
                    results.append(result)
            except Exception as e:
                self.logger.warning(f"Error parsing work package card: {e}")
                self.stats["errors"] += 1

        return results

    def _parse_one_workpackage(self, card):
        """Extract data from a single work package card."""
        # Title and ID
        title_tag = card.find("h4", class_="card-title")
        title = ""
        wp_id = ""
        if title_tag:
            link = title_tag.find("a")
            if link:
                title = link.get_text(strip=True)
                # Extract ID from JS call: showWorkpackageSubscriptionFeature('9508')
                href = link.get("href", "")
                id_match = re.search(r"(\d+)", href)
                if id_match:
                    wp_id = id_match.group(1)

        # Project name (subtitle-bolder)
        project_tag = card.find("h5", class_="subtitle-bolder")
        project_name = project_tag.get_text(strip=True) if project_tag else ""

        # Company / issuing entity (subtitle-upper)
        company_tag = card.find("h5", class_="subtitle-upper")
        company = company_tag.get_text(strip=True) if company_tag else ""

        # Description
        desc_tag = card.find("p", class_="card-text")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Status (Open/Closed)
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
                # Get only the text span, skip the icon span
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

        # PDF/document URL
        pdf_url = ""
        doc_link = card.find("a", class_="card-icon-link")
        if doc_link:
            pdf_url = doc_link.get("href", "")
            # Unescape HTML entities
            pdf_url = pdf_url.replace("&amp;", "&")

        # Date fields and location from dt/dd pairs
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

    def _parse_project_cards(self, html):
        """Parse project cards from HTML."""
        soup = self.parse_html(html)
        cards = soup.find_all("div", class_="card-tile")
        results = []

        for card in cards:
            try:
                result = self._parse_one_project(card)
                if result and result.get("title"):
                    results.append(result)
            except Exception as e:
                self.logger.warning(f"Error parsing project card: {e}")
                self.stats["errors"] += 1

        return results

    def _parse_one_project(self, card):
        """Extract data from a single project card."""
        # Title and ID from link
        title_tag = card.find("h4", class_="card-title")
        title = ""
        project_id = ""
        project_url = ""
        if title_tag:
            link = title_tag.find("a")
            if link:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                # Link format: ./projects/16933/pg-16933
                id_match = re.search(r"/projects/(\d+)", href)
                if id_match:
                    project_id = id_match.group(1)
                    project_url = f"{self.BASE_URL}/projects/{project_id}"
                elif href and not href.startswith("javascript:"):
                    project_url = f"{self.BASE_URL}/{href.lstrip('./')}"

        # Company (subtitle-upper)
        company_tag = card.find("h5", class_="subtitle-upper")
        company = company_tag.get_text(strip=True) if company_tag else ""

        # Description
        desc_tag = card.find("p", class_="card-text")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Work package counts from status badges
        wp_counts = []
        badges = card.find_all("span", class_="status-badge")
        for badge in badges:
            wp_counts.append(badge.get_text(strip=True))
        status = ", ".join(wp_counts) if wp_counts else ""

        # Location from dt/dd
        location = ""
        dl = card.find("dl")
        if dl:
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt_tag, dd_tag in zip(dts, dds):
                label = dt_tag.get_text(strip=True).lower()
                value = dd_tag.get_text(strip=True)
                if "location" in label:
                    location = value

        return {
            "tender_id_external": project_id,
            "title": title,
            "description_raw": description,
            "issuing_entity_name": company,
            "project_name": "",
            "published_date": "",
            "closing_date": "",
            "status": status,
            "region": location,
            "url": project_url,
            "pdf_url": "",
            "type": "project",
            "scope": "",
            "wp_type": "",
            "source": self.name,
            "scraped_at": self.now_iso(),
        }

    def run(self):
        """Main scraper entry point."""
        # Step 1: Load cookies
        if not self._load_cookies():
            return []

        # Step 2: Get CSRF token
        csrf_token = self._get_csrf_token()
        if not csrf_token:
            return []

        all_results = []

        # Step 3: Scrape each type
        for search_type in self.SEARCH_TYPES:
            time.sleep(1)  # Be polite between requests

            html = self._fetch_search_results(csrf_token, search_type)
            if html is None:
                continue

            if not html.strip():
                self.logger.info(f"No results for {search_type}")
                continue

            # Parse based on type
            if search_type == "workpackage":
                items = self._parse_workpackage_cards(html)
            else:
                items = self._parse_project_cards(html)

            self.logger.info(f"Parsed {len(items)} {search_type} items")
            all_results.extend(items)

        # Step 4: Save updated cookies for next run
        self._save_cookies()

        # Step 5: Deduplicate by tender_id + type
        seen = set()
        unique = []
        for item in all_results:
            key = (item.get("tender_id_external", ""), item.get("title", ""), item.get("type", ""))
            if key not in seen:
                seen.add(key)
                unique.append(item)

        self.logger.info(f"Total: {len(unique)} unique items ({len(all_results) - len(unique)} duplicates removed)")
        return unique
