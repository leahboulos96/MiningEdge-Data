================================================================================
  AUSTRALIAN TENDER & ASX ANNOUNCEMENT SCRAPER
  Complete Documentation & Setup Guide
================================================================================

TABLE OF CONTENTS
-----------------
  1.  PROJECT OVERVIEW
  2.  WHAT'S INCLUDED
  3.  SYSTEM REQUIREMENTS
  4.  INSTALLATION (STEP BY STEP)
  5.  CONFIGURATION
  6.  RUNNING THE SCRAPERS
  7.  OUTPUT FILES
  8.  LOG FILES
  9.  FLASK WEB DASHBOARD (BONUS)
  10. CRON SCHEDULING (DAILY AUTOMATION)
  11. ADDING/CHANGING ASX TICKERS
  12. SCRAPER DETAILS PER SOURCE
  13. OUTPUT SCHEMA REFERENCE
  14. ERROR HANDLING & RETRY LOGIC
  15. PERFORMANCE
  16. EXTENDING / CUSTOMIZATION
  17. TROUBLESHOOTING
  18. ACCEPTANCE CRITERIA CHECKLIST
  19. FILE STRUCTURE


================================================================================
1. PROJECT OVERVIEW
================================================================================

This project scrapes:

  A) GOVERNMENT TENDERS from 4 Australian portals:
     1. AusTender (Commonwealth/Federal) - https://www.tenders.gov.au
     2. WA Tenders & Contracts          - https://www.tenders.wa.gov.au
     3. QLD QTenders                     - https://qtenders.hpw.qld.gov.au
     4. SA Tenders & Contracts           - https://www.tenders.sa.gov.au

  B) ICN GATEWAY (Industry Capability Network):
     5. ICN Gateway                      - https://gateway.icn.org.au
     - Scrapes mining-related Projects and Work Packages
     - Requires manual login (2FA) — cookies exported from browser
     - Two options to provide cookies: JSON file or web dashboard

  C) ASX ANNOUNCEMENTS for mining company tickers:
     - Source: ASX company announcements (via markitdigital backend API)
     - Default: 49 mining tickers pre-configured
     - Expandable: Supports 150-250+ tickers
     - PDF links captured but not downloaded (as per spec)

All data is output as JSON files. A bonus Flask web dashboard is included
for running scrapers from a browser, viewing results, and downloading data.


================================================================================
2. WHAT'S INCLUDED
================================================================================

  File/Folder             Description
  ----------------------  ---------------------------------------------------
  run_all_scrapers.py     Single-command entry point (runs ALL scrapers)
  config.py               Configuration (reads from .env file)
  app.py                  Flask web dashboard (bonus feature)
  requirements.txt        Python dependencies
  .env.example            Template for your API keys and credentials
  .gitignore              Git ignore rules
  icn_cookies.json        ICN Gateway session cookies (you create this)

  scrapers/               All scraper code
    base_scraper.py       Base class (proxy, retry, logging, output)
    tenders/
      austender.py        AusTender (Federal) scraper
      wa_tenders.py       WA Tenders scraper
      qld_tenders.py      QLD QTenders scraper
      sa_tenders.py       SA Tenders scraper
      icn_gateway.py      ICN Gateway scraper (cookie-based auth)
    asx/
      asx_scraper.py      ASX announcements scraper

  templates/              HTML templates for the web dashboard
    base.html
    dashboard.html
    login.html
    logs.html
    settings.html
    view_json.html

  output/                 Where JSON output files are saved (auto-created)
  logs/                   Where log files are saved (auto-created)


================================================================================
3. SYSTEM REQUIREMENTS
================================================================================

  - Python 3.8 or higher (tested with Python 3.11)
  - pip (Python package manager)
  - Internet connection
  - A scrape.do account/token (for tender portal scraping)

  Operating System: Works on Windows, macOS, and Linux.


================================================================================
4. INSTALLATION (STEP BY STEP)
================================================================================

  STEP 1: Open a terminal/command prompt and navigate to the project folder.

      cd /path/to/this/project

  STEP 2: (Recommended) Create a Python virtual environment.

      python -m venv venv

      On Windows:
          venv\Scripts\activate

      On macOS/Linux:
          source venv/bin/activate

  STEP 3: Install dependencies.

      pip install -r requirements.txt

  STEP 4: Set up your environment file.

      Copy the .env.example file to .env:

      On Windows:
          copy .env.example .env

      On macOS/Linux:
          cp .env.example .env

  STEP 5: Edit the .env file with your actual credentials.

      Open .env in any text editor and fill in:
        - SCRAPE_DO_TOKEN     (your scrape.do API token)
        - ASX_ACCESS_TOKEN    (the ASX public token - pre-filled in .env.example)
        - ADMIN_USERNAME      (dashboard login username)
        - ADMIN_PASSWORD      (dashboard login password)
        - FLASK_SECRET_KEY    (any random string for session security)

      See Section 5 (Configuration) for details on each setting.

  STEP 6: Set up ICN Gateway cookies (if using ICN Gateway).

      ICN Gateway requires manual login (2FA). See Section 5.1 below for
      detailed instructions. You can provide cookies in two ways:
        a) Create icn_cookies.json in the project root (for CLI usage)
        b) Paste cookies in the web dashboard Settings page (for web usage)

  STEP 7: Run the scrapers.

      python run_all_scrapers.py

  That's it! Output files will appear in the output/ folder and logs in logs/.


================================================================================
5. CONFIGURATION
================================================================================

  All configuration is done via the .env file. No code changes are needed.

  ---- .env FILE SETTINGS ----

  SCRAPE_DO_TOKEN
      Your scrape.do proxy API token. This is REQUIRED for tender scraping.
      The tender portals may block direct requests, so scrape.do acts as a
      proxy to avoid rate limiting and blocking.
      Sign up at: https://scrape.do
      Free tier available for testing.

  ASX_ACCESS_TOKEN
      The public API token used by the ASX website for company announcements.
      Pre-filled in .env.example with the current public token:
          83ff96335c2d45a094df02a206a39ff4
      This is NOT a private API key - it's the same token the ASX website
      uses in the browser. No license needed.

  FLASK_SECRET_KEY
      A random string used by Flask for session security.
      Only matters if you use the web dashboard.
      Set to any long random string, e.g.: my-super-secret-key-2026

  ADMIN_USERNAME
      Username for the web dashboard login. Default: admin

  ADMIN_PASSWORD
      Password for the web dashboard login. Default: admin123
      IMPORTANT: Change this if you deploy the dashboard on a server.

  ---- ADDITIONAL SETTINGS IN config.py ----

  These are pre-configured and generally don't need changing:

  MAX_RETRIES = 3           Retry failed HTTP requests up to 3 times
  RETRY_BACKOFF = 2         Wait 2 seconds before first retry (doubles each)
  ASX_ANNOUNCEMENTS_COUNT   Number of announcements per ticker (default: 50)
  ASX_RATE_LIMIT_DELAY      Seconds between ticker requests (default: 0.5)
  ASX_TICKERS               Default list of 49 mining tickers (editable)


================================================================================
5.1 ICN GATEWAY COOKIE SETUP
================================================================================

  ICN Gateway (gateway.icn.org.au) requires two-factor authentication (2FA)
  to log in, which means the scraper cannot log in automatically. Instead,
  you must log in via your browser and provide the session cookies.

  There are TWO ways to provide cookies:

  ---- OPTION A: JSON FILE (for command-line usage) ----

  1. Open Chrome and go to https://gateway.icn.org.au
  2. Log in with your credentials + 2FA code
  3. Once logged in, open DevTools:
       Press F12 (or right-click > Inspect)
  4. Go to: Application tab > Cookies > https://gateway.icn.org.au
  5. Find and copy the values of these 4 cookies:
       - PHPSESSID
       - remember_tfa_gateway
       - XSRF-TOKEN
       - gateway_by_icn_session
  6. Create a file called icn_cookies.json in the project root folder:

      {
        "PHPSESSID": "paste_value_here",
        "remember_tfa_gateway": "paste_value_here",
        "XSRF-TOKEN": "paste_value_here",
        "gateway_by_icn_session": "paste_value_here"
      }

  7. Run the scraper. The file will be auto-updated as cookies rotate.

  ---- OPTION B: WEB DASHBOARD (for browser-based usage) ----

  1. Start the dashboard: python app.py
  2. Log in and go to Settings
  3. Scroll down to the "ICN Gateway Cookies" section
  4. Paste the 4 cookie values into the input fields
  5. Click Save Settings
  6. The cookies are saved to icn_cookies.json automatically

  ---- IMPORTANT NOTES ----

  - Sessions typically last several hours (sometimes longer with the
    remember_tfa_gateway cookie)
  - If the scraper reports "session expired", re-export fresh cookies
  - The scraper automatically saves updated cookies after each run,
    so you don't need to re-export every time
  - The cookie file (icn_cookies.json) is excluded from git for security


================================================================================
6. RUNNING THE SCRAPERS
================================================================================

  ---- RUN ALL SCRAPERS AT ONCE ----

      python run_all_scrapers.py

  This runs all 6 scrapers sequentially:
    1. AusTender (Federal)
    2. WA Tenders
    3. QLD QTenders
    4. SA Tenders
    5. ICN Gateway (requires cookies — see Section 5.1)
    6. ASX Announcements

  After completion, you'll see a summary like:

      ============================================================
        SUMMARY
      ============================================================
        AusTender (Federal)              45 items  [OK]
        WA Tenders                       23 items  [OK]
        QLD QTenders                     67 items  [OK]
        SA Tenders                       31 items  [OK]
        ICN Gateway                      24 items  [OK]
        ASX Announcements              1250 items  [OK]

        TOTAL                          1440 items  [0 errors]
        Runtime: 90.5s
        Finished: 2026-02-15 06:00:45
      ============================================================

  ---- RUN INDIVIDUAL SCRAPERS ----

  You can run each scraper independently:

      python -m scrapers.tenders.austender
      python -m scrapers.tenders.wa_tenders
      python -m scrapers.tenders.qld_tenders
      python -m scrapers.tenders.sa_tenders
      python -m scrapers.tenders.icn_gateway
      python -m scrapers.asx.asx_scraper

  This is useful for testing individual portals or re-running a failed one.


================================================================================
7. OUTPUT FILES
================================================================================

  Output JSON files are saved to the output/ folder with date stamps:

      output/austender_YYYYMMDD.json
      output/wa_tenders_YYYYMMDD.json
      output/qld_tenders_YYYYMMDD.json
      output/sa_tenders_YYYYMMDD.json
      output/icn_gateway_YYYYMMDD.json
      output/asx_announcements_YYYYMMDD.json

  Example: output/austender_20260215.json

  Each file contains a JSON array of objects. Example tender record:

      [
        {
          "tender_id_external": "ATM12345",
          "title": "Supply of Mining Equipment",
          "description_raw": "Request for tender for ...",
          "issuing_entity_name": "Department of Defence",
          "published_date": "Mon, 10 Feb 2026 00:00:00 GMT",
          "closing_date": "28 Feb 2026",
          "status": "Open",
          "region": "",
          "url": "https://www.tenders.gov.au/atm/show/...",
          "source": "austender",
          "scraped_at": "2026-02-15T06:00:12.345678+00:00"
        }
      ]

  Example ASX announcement record:

      [
        {
          "ticker": "BHP",
          "company_name_raw": "BHP GROUP LIMITED",
          "announcement_title": "Half Year Results",
          "announcement_date": "2026-02-14T08:30:00+1100",
          "announcement_type": "Company Report",
          "url": "https://www.asx.com.au/announcements/pdf/...",
          "pdf_url": "https://cdn-api.markitdigital.com/...",
          "is_price_sensitive": true,
          "file_size": "1.2 MB",
          "snippet_raw": "",
          "scraped_at": "2026-02-15T06:05:32.123456+00:00"
        }
      ]

  NOTE: If you run the scrapers multiple times on the same day, the output
  file for that day will be overwritten with the latest data.


================================================================================
8. LOG FILES
================================================================================

  Log files are saved to the logs/ folder with date stamps:

      logs/austender_YYYY-MM-DD.log
      logs/wa_tenders_YYYY-MM-DD.log
      logs/qld_tenders_YYYY-MM-DD.log
      logs/sa_tenders_YYYY-MM-DD.log
      logs/icn_gateway_YYYY-MM-DD.log
      logs/asx_announcements_YYYY-MM-DD.log

  Example: logs/austender_2026-02-15.log

  Each log file contains:
    - Start timestamp
    - Number of items found per page/step
    - HTTP errors and retry attempts
    - Total items scraped
    - End timestamp and error count

  Example log content:

      2026-02-15 06:00:01 [austender] INFO: === Starting austender scraper ===
      2026-02-15 06:00:01 [austender] INFO: Fetching AusTender RSS feed...
      2026-02-15 06:00:03 [austender] INFO: Found 45 items in RSS feed
      2026-02-15 06:00:03 [austender] DEBUG: Scraped: ATM12345 - Supply of Mining Equip...
      ...
      2026-02-15 06:00:45 [austender] INFO: Saved 45 records to output/austender_20260215.json
      2026-02-15 06:00:45 [austender] INFO: === Finished austender: 45 items, 0 errors ===


================================================================================
9. FLASK WEB DASHBOARD (BONUS)
================================================================================

  A web-based dashboard is included as a bonus feature. It is NOT required
  to run the scrapers - the command line works perfectly on its own.

  ---- STARTING THE DASHBOARD ----

      python app.py

  Then open your browser to: http://localhost:5000

  ---- LOGIN ----

      Default credentials (change in .env file):
        Username: admin
        Password: admin123

  ---- DASHBOARD FEATURES ----

    - Run All Scrapers: One-click to run all 6 scrapers
    - Run Individual: Run any single scraper from the browser
    - Live Status: See running/completed/error status for each scraper
    - Output Files: View, download (JSON/CSV/XLSX), or delete output files
    - Log Viewer: Browse and read log files from the browser
    - Settings: Configure scrape.do token, ASX tickers, ICN Gateway cookies,
                enable/disable scrapers, and set up daily scheduled runs
    - Auto-Refresh: Dashboard auto-updates every 3 seconds while scrapers run

  ---- DASHBOARD SETTINGS PAGE ----

    The Settings page lets you:
      1. Change your scrape.do API token
      2. Edit the list of ASX tickers (comma-separated)
      3. Configure ICN Gateway cookies (paste from browser)
      4. Enable/disable individual scrapers
      5. Enable daily scheduling (set hour and minute)

    Settings are saved to settings.json (excluded from git).

  NOTE: The dashboard uses Flask's built-in threading. For production use
  behind a reverse proxy (nginx), use gunicorn:

      gunicorn app:app --bind 0.0.0.0:5000 --workers 1 --threads 4


================================================================================
10. CRON SCHEDULING (DAILY AUTOMATION)
================================================================================

  To run the scrapers automatically every day, set up a cron job.

  ---- LINUX / macOS ----

  Open crontab:
      crontab -e

  Add this line (runs daily at 6:00 AM):
      0 6 * * * cd /path/to/project && /path/to/venv/bin/python run_all_scrapers.py >> /var/log/scraper_cron.log 2>&1

  If using a virtual environment, make sure to use the full path to python:
      0 6 * * * cd /home/user/scraper && /home/user/scraper/venv/bin/python run_all_scrapers.py >> /var/log/scraper_cron.log 2>&1

  ---- WINDOWS (Task Scheduler) ----

  1. Open Task Scheduler (search "Task Scheduler" in Start menu)
  2. Click "Create Basic Task"
  3. Name: "Daily Scraper Run"
  4. Trigger: Daily at 6:00 AM
  5. Action: Start a Program
     Program: C:\path\to\venv\Scripts\python.exe
     Arguments: run_all_scrapers.py
     Start in: C:\path\to\project

  ---- ALTERNATIVE: Use the Dashboard Scheduler ----

  The Flask dashboard has a built-in scheduler. Go to Settings and:
  1. Check "Enable daily scheduled run"
  2. Set the hour and minute
  3. Click Save
  This only works while the dashboard is running (python app.py).


================================================================================
11. ADDING/CHANGING ASX TICKERS
================================================================================

  ---- METHOD 1: Edit config.py ----

  Open config.py and modify the ASX_TICKERS list:

      ASX_TICKERS = [
          "BHP", "RIO", "FMG", "MIN", "S32",
          ... add your tickers here ...
      ]

  ---- METHOD 2: Use the Dashboard ----

  1. Start the dashboard: python app.py
  2. Login and go to Settings
  3. Edit the "Mining Tickers" textarea (comma-separated)
  4. Click Save

  ---- CURRENT DEFAULT TICKERS (49) ----

  BHP, RIO, FMG, MIN, S32, NCM, NST, EVN, OZL, IGO, SFR, PLS, LTR,
  AGY, LYC, ILU, ORE, AVZ, CXO, GL1, SYA, TLG, NMT, VUL, AKE, DEG,
  GOR, RMS, CMM, RED, SLR, WAF, PRU, RSG, WGX, TIE, KAI, BGL, MML,
  PNR, CRN, LNR, AIS, 29M, ASM, NHC, WHC, YAL, TIG

  You can expand this to 150-250+ tickers. At 0.5s rate limiting per
  ticker, 250 tickers takes approximately 2-3 minutes to complete.


================================================================================
12. SCRAPER DETAILS PER SOURCE
================================================================================

  ---- 1. AUSTENDER (FEDERAL) ----
  URL:    https://www.tenders.gov.au
  Method: Fetches RSS feed, then scrapes detail pages for extra fields
  Proxy:  Yes (scrape.do)
  Output: output/austender_YYYYMMDD.json

  ---- 2. WA TENDERS ----
  URL:    https://www.tenders.wa.gov.au
  Method: Session-based with CSRF token, POST search for open tenders,
          parses HTML table results with pagination
  Proxy:  Yes (scrape.do)
  Output: output/wa_tenders_YYYYMMDD.json

  ---- 3. QLD QTENDERS ----
  URL:    https://qtenders.hpw.qld.gov.au
  Method: Obtains antiforgery token from homepage, then POSTs to JSON API
          with pagination
  Proxy:  Yes (scrape.do)
  Output: output/qld_tenders_YYYYMMDD.json

  ---- 4. SA TENDERS ----
  URL:    https://www.tenders.sa.gov.au
  Method: Fetches search results HTML, parses table listings, then
          scrapes detail pages for up to 50 tenders for full field data
  Proxy:  Yes (scrape.do)
  Output: output/sa_tenders_YYYYMMDD.json

  ---- 5. ICN GATEWAY ----
  URL:    https://gateway.icn.org.au
  Method: Cookie-based authentication (manual login with 2FA required).
          Fetches CSRF token from projects page, then uses AJAX POST
          with X-AJAX-HANDLER header to search for mining-related
          projects and work packages. Parses HTML card responses.
  Proxy:  No (direct requests with session cookies)
  Auth:   Session cookies from icn_cookies.json (see Section 5.1)
  Types:  Work Packages (open tenders) and Projects (parent projects)
  Output: output/icn_gateway_YYYYMMDD.json

  ---- 6. ASX ANNOUNCEMENTS ----
  URL:    https://asx.api.markitdigital.com (ASX backend API)
  Method: Direct JSON API calls per ticker (no proxy needed)
  Proxy:  No
  Output: output/asx_announcements_YYYYMMDD.json


================================================================================
13. OUTPUT SCHEMA REFERENCE
================================================================================

  ---- TENDER FIELDS ----

  Field                 Type     Description
  --------------------  -------  -----------------------------------------------
  tender_id_external    string   Official tender reference/ID
  title                 string   Tender headline
  description_raw       string   Raw description text
  issuing_entity_name   string   Department/agency/entity
  published_date        string   Date the tender was opened/published
  closing_date          string   Deadline for submissions
  status                string   Open/Closed/Cancelled
  region                string   State/territory (WA, QLD, SA, or auto-detected)
  url                   string   Direct link to the tender
  source                string   Which portal (austender, wa_tenders, etc.)
  scraped_at            string   ISO timestamp of when it was scraped

  ---- ICN GATEWAY FIELDS ----

  Field                 Type     Description
  --------------------  -------  -----------------------------------------------
  tender_id_external    string   ICN project/work package ID
  title                 string   Project or work package title
  description_raw       string   Raw description text
  issuing_entity_name   string   Company name (e.g. LIONTOWN RESOURCES LIMITED)
  project_name          string   Parent project name (work packages only)
  published_date        string   EOI open date (work packages only)
  closing_date          string   EOI close date (work packages only)
  status                string   Open/Closed (work packages) or WP counts (projects)
  region                string   Location (e.g. "WA Australia")
  url                   string   Direct link to the ICN Gateway page
  pdf_url               string   Link to attached document (if available)
  type                  string   "workpackage" or "project"
  scope                 string   Scope level (e.g. "Full Scope / Partial Scope")
  wp_type               string   Work package type (e.g. "standard")
  source                string   Always "icn_gateway"
  scraped_at            string   ISO timestamp of when it was scraped

  Example ICN Gateway record:

      {
        "tender_id_external": "9508",
        "title": "Underground Mine Services Area Bulk Earthworks",
        "description_raw": "Please refer to the Scope of Works...",
        "issuing_entity_name": "LIONTOWN RESOURCES LIMITED",
        "project_name": "Kathleen Valley Lithium-Tantalum Project",
        "published_date": "13 Feb 2026",
        "closing_date": "27 Feb 2026",
        "status": "Open",
        "region": "WA Australia",
        "url": "https://gateway.icn.org.au/projects/9508",
        "pdf_url": "https://gateway-files-prd.icn.org.au/attachments/...",
        "type": "workpackage",
        "scope": "Full Scope",
        "wp_type": "standard",
        "source": "icn_gateway",
        "scraped_at": "2026-02-18T09:57:20+00:00"
      }

  ---- ASX ANNOUNCEMENT FIELDS ----

  Field                 Type     Description
  --------------------  -------  -----------------------------------------------
  ticker                string   ASX ticker code (e.g. BHP)
  company_name_raw      string   Company display name from ASX
  announcement_title    string   Announcement headline
  announcement_date     string   Date/time of announcement
  announcement_type     string   Type (e.g. Company Report, Price Sensitive)
  url                   string   Link to the announcement
  pdf_url               string   Direct link to the PDF document
  is_price_sensitive    boolean  Whether ASX flagged it as price sensitive
  file_size             string   Size of the PDF document
  snippet_raw           string   Summary text (if available from API)
  scraped_at            string   ISO timestamp of when it was scraped


================================================================================
14. ERROR HANDLING & RETRY LOGIC
================================================================================

  - All HTTP requests are retried up to 3 times on failure
  - Retry backoff: 2 seconds, then 4 seconds, then 8 seconds
  - Client errors (HTTP 4xx) are NOT retried (they won't succeed on retry)
  - Server errors (HTTP 5xx) and network errors ARE retried
  - Each scraper catches all exceptions and logs them without crashing
  - If one scraper fails, the others still run (run_all_scrapers.py)
  - The run_all_scrapers.py exit code indicates errors:
      Exit 0 = all scrapers completed without errors
      Exit 1 = one or more scrapers had errors
  - All errors are logged to both the console and the log files


================================================================================
15. PERFORMANCE
================================================================================

  Expected runtimes (approximate):

  Scraper              Expected Runtime    Expected Records/Day
  -------------------  ------------------  ----------------------
  AusTender            30-90 seconds       10-50 tenders
  WA Tenders           15-60 seconds       5-20 tenders
  QLD QTenders         10-30 seconds       5-30 tenders
  SA Tenders           30-120 seconds      5-20 tenders
  ICN Gateway          5-15 seconds        20-80 items
  ASX (49 tickers)     25-60 seconds       500-1500 announcements
  ASX (250 tickers)    2-4 minutes         1000-3000 announcements
  -------------------  ------------------  ----------------------
  TOTAL (49 tickers)   2-6 minutes         ~545-1700 records

  All government portals should complete in under 5 minutes total.
  ASX with 200+ tickers should complete in under 10 minutes.
  Total daily volume is well under 1,500 records with default tickers.


================================================================================
16. EXTENDING / CUSTOMIZATION
================================================================================

  ---- ADDING A NEW SCRAPER ----

  1. Create a new file under scrapers/tenders/ or scrapers/asx/
  2. Inherit from BaseScraper
  3. Set a unique "name" class variable
  4. Implement the run() method (must return a list of dicts)
  5. Add it to run_all_scrapers.py and SCRAPER_MAP in app.py

  Example skeleton:

      from scrapers.base_scraper import BaseScraper

      class MyNewScraper(BaseScraper):
          name = "my_new_scraper"

          def run(self):
              results = []
              # ... your scraping logic ...
              return results

      if __name__ == "__main__":
          scraper = MyNewScraper()
          scraper.execute()

  ---- CHANGING OUTPUT FORMAT ----

  Output is JSON by default. The dashboard also supports CSV and XLSX
  downloads. To change the default format, modify the save_output()
  method in scrapers/base_scraper.py.

  ---- ADJUSTING RATE LIMITS ----

  Edit .env or config.py:
    ASX_RATE_LIMIT_DELAY = 0.5   (seconds between ASX ticker requests)
    RETRY_BACKOFF = 2            (seconds before first retry)


================================================================================
17. TROUBLESHOOTING
================================================================================

  ---- "ModuleNotFoundError: No module named 'dotenv'" ----
  Run: pip install python-dotenv

  ---- "ModuleNotFoundError: No module named 'lxml'" ----
  Run: pip install lxml
  On some systems you may need: pip install lxml --only-binary :all:

  ---- Tender scrapers return 0 results ----
  1. Check that SCRAPE_DO_TOKEN is set correctly in your .env file
  2. Verify your scrape.do account has API credits remaining
  3. Check the log file for HTTP error codes
  4. Some portals may temporarily block requests - wait and retry

  ---- ASX scraper returns 0 results ----
  1. Check that ASX_ACCESS_TOKEN is set in your .env file
  2. The default token (83ff96335c2d45a094df02a206a39ff4) should work
  3. If ASX changes their token, check the ASX website network requests
     to find the current token

  ---- ICN Gateway: "Session expired" or "Cookie file not found" ----
  1. ICN Gateway requires manual login (2FA). The scraper cannot log in
     automatically.
  2. Log in to https://gateway.icn.org.au in your browser
  3. Export the 4 cookies (see Section 5.1 for detailed instructions)
  4. Either paste them in the web dashboard Settings page, or save them
     to icn_cookies.json in the project root
  5. Sessions typically last several hours. If scraping fails with
     "session expired", repeat the login and cookie export process.

  ---- ICN Gateway: Returns 0 results ----
  1. Check that icn_cookies.json exists and has all 4 required cookies
  2. Check the log file (logs/icn_gateway_YYYY-MM-DD.log) for errors
  3. Try refreshing cookies — the session may have expired
  4. The search keyword is "mining" (configured in config.py as
     ICN_SEARCH_KEYWORDS). Change it if needed.

  ---- "Connection refused" or timeout errors ----
  1. Check your internet connection
  2. Some government portals may have maintenance windows
  3. The scraper retries 3 times automatically
  4. If persistent, check if the portal URL has changed

  ---- Dashboard won't start ----
  1. Make sure Flask is installed: pip install flask
  2. Check if port 5000 is already in use
  3. Try a different port: set PORT=8080 and run python app.py

  ---- "Permission denied" on log/output files ----
  Make sure the logs/ and output/ directories are writable.
  They are auto-created by config.py if they don't exist.

  ---- How to check if scrape.do token works ----
  Open this URL in your browser (replace YOUR_TOKEN):
  https://api.scrape.do/?token=YOUR_TOKEN&url=https://www.tenders.gov.au
  If you see HTML content, your token works.


================================================================================
18. ACCEPTANCE CRITERIA CHECKLIST
================================================================================

  TENDERS:
  [x] AusTender (Federal) scraped successfully
  [x] WA Tenders scraped successfully
  [x] QLD QTenders scraped successfully
  [x] SA Tenders scraped successfully
  [x] ICN Gateway scraped successfully (projects + work packages)
  [x] Required fields captured (tender_id, title, description, entity,
      published_date, closing_date, status, region, url, scraped_at)
  [x] JSON output produced per portal
  [x] Logs generated per portal per day
  [x] Scripts run without errors (on valid configuration)

  ASX:
  [x] All configured tickers produce announcements
  [x] Titles, dates, URLs extracted
  [x] PDF links captured
  [x] No duplicates within a run (deduplication by document key)

  GENERAL:
  [x] All scripts documented (this README)
  [x] One-command execution: python run_all_scrapers.py
  [x] Error handling with 3x retry + exponential backoff
  [x] Logging to files with timestamps
  [x] Code is modular and extendable (BaseScraper + per-portal classes)
  [x] requirements.txt provided
  [x] No hardcoded credentials (all in .env file)

  ICN GATEWAY:
  [x] Cookie-based authentication (2FA portal)
  [x] Work packages and projects both scraped
  [x] Automatic cookie rotation (saves updated cookies after each run)
  [x] CSRF token extraction and refresh on expiry
  [x] Two ways to configure cookies: JSON file or web dashboard

  BONUS (beyond requirements):
  [x] Flask web dashboard with login
  [x] Browser-based scraper execution
  [x] CSV and XLSX download support
  [x] Built-in daily scheduler
  [x] Settings management via web UI (including ICN cookie management)


================================================================================
19. FILE STRUCTURE
================================================================================

  project/
  |
  |-- run_all_scrapers.py         Main entry point
  |-- config.py                   Configuration (reads .env)
  |-- app.py                      Flask web dashboard
  |-- requirements.txt            Python dependencies
  |-- .env.example                Template for credentials
  |-- .gitignore                  Git ignore rules
  |-- icn_cookies.json            ICN Gateway session cookies (you create this)
  |-- README.txt                  This file
  |
  |-- scrapers/
  |   |-- __init__.py
  |   |-- base_scraper.py         Base class for all scrapers
  |   |
  |   |-- tenders/
  |   |   |-- __init__.py
  |   |   |-- austender.py        AusTender (Federal)
  |   |   |-- wa_tenders.py       WA Tenders
  |   |   |-- qld_tenders.py      QLD QTenders
  |   |   |-- sa_tenders.py       SA Tenders
  |   |   |-- icn_gateway.py      ICN Gateway (cookie-based auth)
  |   |
  |   |-- asx/
  |       |-- __init__.py
  |       |-- asx_scraper.py      ASX Announcements
  |
  |-- templates/
  |   |-- base.html               Dashboard base template
  |   |-- dashboard.html          Main dashboard page
  |   |-- login.html              Login page
  |   |-- logs.html               Log viewer page
  |   |-- settings.html           Settings page
  |   |-- view_json.html          JSON viewer page
  |
  |-- output/                     JSON output files (auto-created)
  |-- logs/                       Log files (auto-created)


================================================================================
  END OF DOCUMENTATION
================================================================================
