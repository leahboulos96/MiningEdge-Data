"""
CLI entry point for running every registered scraper once.
Failures in one scraper never stop the rest; every run is recorded in the
unified DB (miningedge.db) and as a dated JSON snapshot in output/.

Usage:
    python run_all_scrapers.py                # all scrapers
    python run_all_scrapers.py tenders        # one group
    python run_all_scrapers.py austender asx_announcements
"""

import sys
import time
from datetime import datetime

import db
import registry
import scheduler as sched_mod


def main():
    db.init_db()

    args = sys.argv[1:]
    if not args:
        keys = registry.all_keys()
    else:
        targets = []
        for a in args:
            if a in registry.groups():
                targets.append(f"group:{a}")
            else:
                targets.append(a)
        keys = registry.resolve_targets(targets)

    start = time.time()
    print(f"\n{'='*60}\n  MiningEdge - CLI run\n  Started: "
          f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{'='*60}")

    summary = []
    for key in keys:
        print(f"\n--- {registry.label(key)} ---")
        result = sched_mod.run_single_scraper(key, triggered_by="cli")
        summary.append((registry.label(key), result))
        print(f"  -> {result.get('found',0)} found | "
              f"{result.get('new',0)} new | "
              f"{result.get('skipped',0)} skipped | "
              f"status={result.get('status')}")

    print(f"\n{'='*60}\n  SUMMARY\n{'='*60}")
    total_new = 0
    errors = 0
    for label, r in summary:
        status = r.get("status")
        flag = "OK" if status == "ok" else status.upper()
        print(f"  {label:32s} new={r.get('new',0):4d}  [{flag}]")
        total_new += r.get("new", 0)
        if status != "ok":
            errors += 1
    print(f"\n  TOTAL NEW: {total_new}   Errors: {errors}   "
          f"Runtime: {time.time()-start:.1f}s\n")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
