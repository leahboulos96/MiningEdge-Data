"""
Single-command entry point to run all scrapers.
Usage: python run_all_scrapers.py
"""

import sys
import time
from datetime import datetime

from scrapers.tenders.austender import AusTenderScraper
from scrapers.tenders.wa_tenders import WATendersScraper
from scrapers.tenders.qld_tenders import QLDTendersScraper
from scrapers.tenders.sa_tenders import SATendersScraper
from scrapers.tenders.icn_gateway import ICNGatewayScraper
from scrapers.asx.asx_scraper import ASXScraper


def main():
    start = time.time()
    print(f"\n{'='*60}")
    print(f"  Australian Tender & ASX Scraper")
    print(f"  Run started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    scrapers = [
        ("AusTender (Federal)", AusTenderScraper),
        ("WA Tenders", WATendersScraper),
        ("QLD QTenders", QLDTendersScraper),
        ("SA Tenders", SATendersScraper),
        ("ICN Gateway", ICNGatewayScraper),
        ("ASX Announcements", ASXScraper),
    ]

    summary = []

    for label, scraper_cls in scrapers:
        print(f"\n--- {label} ---")
        scraper = scraper_cls()
        results = scraper.execute()
        count = len(results) if results else 0
        errors = scraper.stats.get("errors", 0)
        summary.append((label, count, errors))
        print(f"  -> {count} items, {errors} errors")

    elapsed = time.time() - start

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    total_items = 0
    total_errors = 0
    for label, count, errors in summary:
        status = "OK" if errors == 0 else f"{errors} ERRORS"
        print(f"  {label:30s} {count:6d} items  [{status}]")
        total_items += count
        total_errors += errors

    print(f"  {'':30s} {'':6s}")
    print(f"  {'TOTAL':30s} {total_items:6d} items  [{total_errors} errors]")
    print(f"  Runtime: {elapsed:.1f}s")
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
