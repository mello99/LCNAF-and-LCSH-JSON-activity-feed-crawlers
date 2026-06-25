#!/usr/bin/env python3
"""
LCNAF Activity Stream Feed Crawler
====================================
Finds and saves all feed pages containing items published on one or more
target dates.

How it works
------------
1. SEEK phase  — starts at feed page 1 (the most recent) and follows "next"
                 links backward in time. It keeps going as long as the
                 OLDEST target date (--end-date) is still present on the
                 page, and stops as soon as a page no longer contains it
                 (or there are no more pages). The last page that still
                 contained the oldest target date is the starting point
                 for phase 2.
2. SAVE phase  — from that page, follows "prev" links forward in time, saving
                 every page that contains any target date, and stops once the
                 NEWEST target date (--start-date) has been passed.

Usage
-----
    python3 lcnaf_crawler.py [options]

Options
-------
    --start-url URL     Feed page to begin seeking from.
                        Default: http://id.loc.gov/authorities/names/activitystreams/feed/1
    --output-dir DIR    Directory to save feed files (default: ./feeds)
    --delay FLOAT       Seconds to wait between requests (default: 10)
    --dry-run           Print matching pages without saving them
    --date DATE         Single date to look for (YYYY-MM-DD). Defaults to
                        today if neither --date nor --start-date is given.
    --start-date DATE   Start (newest) date of a range (YYYY-MM-DD). Use with --end-date.
    --end-date DATE     End (oldest) date of a range (YYYY-MM-DD, inclusive).

Examples
--------
    # Download all feed pages that contain today's records
    python3 lcnaf_crawler.py

    # Download pages for a single past date
    python3 lcnaf_crawler.py --date 2026-06-12

    # Download pages for a date range
    python3 lcnaf_crawler.py --start-date 2026-06-14 --end-date 2026-06-12

    # Dry run to preview what would be saved
    python3 lcnaf_crawler.py --start-date 2026-06-14 --end-date 2026-06-12 --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date, timedelta


def fetch_json(url: str, delay: float = 0.0):
    """Fetch a URL and return (parsed_dict, raw_bytes), or (None, None) on error."""
    if delay:
        time.sleep(delay)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8")), raw
    except (urllib.error.URLError, json.JSONDecodeError, Exception) as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}", file=sys.stderr)
        return None, None


def safe_filename(url: str, date_str: str) -> str:
    """Convert a feed URL to a filename, e.g. LCNAF_Activity_Stream_97_2026-06-12.json"""
    m = re.search(r"/feed/(\d+)$", url)
    feed_num = m.group(1) if m else re.sub(r"[^\w]", "_", url)[-20:]
    return f"LCNAF_Activity_Stream_{feed_num}_{date_str}.json"


def validate_date(date_str: str) -> str:
    """Validate YYYY-MM-DD format for argparse."""
    try:
        date.fromisoformat(date_str)
        return date_str
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{date_str}'. Expected format: YYYY-MM-DD (e.g. 2026-06-12)"
        )


def save_page(url: str, raw_bytes: bytes, matching_dates: set, output_dir: str, dry_run: bool):
    """Save a feed page to disk, or print path if dry_run."""
    date_label = sorted(matching_dates)[0]
    filename = safe_filename(url, date_label)
    dest = os.path.join(output_dir, filename)
    if dry_run:
        print(f"  [DRY RUN] Would save: {dest}  (matched: {sorted(matching_dates)})")
    else:
        os.makedirs(output_dir, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(raw_bytes)
        print(f"  [SAVED] {dest}  (matched: {sorted(matching_dates)})")


def crawl(start_url, output_dir, delay, dry_run, target_dates):
    oldest_target = min(target_dates)   # seek stops here  (e.g. 2026-06-12)
    newest_target = max(target_dates)   # save stops after (e.g. 2026-06-14)

    print(f"Target date(s): {', '.join(sorted(target_dates))}")
    print(f"Seeking back to : {oldest_target}")
    print(f"Saving forward to: {newest_target}")
    print(f"Start URL     : {start_url}")
    print(f"Output dir    : {output_dir}")
    print(f"Dry run       : {dry_run}")
    print("-" * 60)

    pages_visited = 0
    pages_saved   = 0
    pages_skipped = 0

    # -------------------------------------------------------------------------
    # PHASE 1 — SEEK BACKWARD
    # feed/1 is the newest page; "next" links go further back in time.
    #
    # IMPORTANT: a single feed page can contain a range of dates, and the
    # oldest target date may appear on several consecutive pages (e.g. pages
    # 1 through 5 might all contain items published on 2026-06-25, with page
    # 5 being the LAST page (furthest back in time) where it still appears).
    #
    # We must not stop at the FIRST page where the oldest target date shows
    # up — we need to keep following "next" until the date is no longer
    # present (or we run out of pages), and use the LAST page where it was
    # still found as the starting point for phase 2.
    # -------------------------------------------------------------------------
    print("\n=== PHASE 1: Seeking backward from feed/1 ===\n")

    first_match_page = None
    first_match_raw  = None
    first_match_url  = None
    current_url      = start_url

    while current_url:
        print(f"[SEEK] {current_url}")
        page, raw_bytes = fetch_json(current_url, delay=delay)
        if page is None:
            print("  Could not load page; stopping.")
            return

        pages_visited += 1
        items         = page.get("orderedItems", [])
        dates_on_page = {item.get("published", "") for item in items}
        clean_dates   = sorted(d for d in dates_on_page if d)

        if oldest_target in dates_on_page:
            print(f"  [MATCH] Oldest target date {oldest_target!r} found here.")
            # This is our best candidate so far for where phase 2 should
            # start, but an even OLDER page might still contain this date
            # too, so keep seeking backward.
            first_match_page = page
            first_match_raw  = raw_bytes
            first_match_url  = current_url

            next_url = page.get("next")
            if not next_url:
                print("  No older pages exist; this is the oldest page available.")
                break
            current_url = next_url
        else:
            if first_match_page is not None:
                # We've already found at least one matching page, and this
                # newer-in-the-backward-walk... no — this page is OLDER
                # (we just followed "next") and no longer has the date.
                # That means the previous page we stored is the correct,
                # oldest page that still contains the target date.
                print(f"  [STOP] Oldest target date no longer present here.")
                print(f"  Using last matching page as the start of phase 2.")
                break
            print(f"  [SKIP]  Not here yet. Dates on page: {clean_dates}")
            pages_skipped += 1
            current_url = page.get("next")   # "next" = older pages

    if first_match_page is None:
        print("\nOldest target date not found in any feed page. Nothing to save.")
        return

    # -------------------------------------------------------------------------
    # PHASE 2 — SAVE FORWARD
    # "prev" links move toward newer pages (lower feed numbers).
    # Save every page that contains any target date.
    # Stop once the page's dates have all moved past the newest target date.
    # -------------------------------------------------------------------------
    print("\n=== PHASE 2: Saving forward from first matching page ===\n")

    current_url  = first_match_url
    current_page = first_match_page
    raw_bytes    = first_match_raw

    while True:
        items         = current_page.get("orderedItems", [])
        dates_on_page = {item.get("published", "") for item in items}
        clean_dates   = sorted(d for d in dates_on_page if d)
        matching      = target_dates & dates_on_page

        print(f"[SAVE] {current_url}  —  dates on page: {clean_dates}")

        if matching:
            save_page(current_url, raw_bytes, matching, output_dir, dry_run)
            pages_saved += 1
        else:
            print(f"  [DONE] No target dates on this page.")
            print("  Stopping — all matching pages have been collected.")
            break

        # If every date on this page is already newer than newest_target,
        # we've collected everything we need.
        if clean_dates and min(clean_dates) > newest_target:
            print(f"  [DONE] Page has moved past newest target {newest_target!r}.")
            print("  Stopping — all matching pages have been collected.")
            break

        prev_url = current_page.get("prev")   # "prev" = newer pages
        if not prev_url:
            print("  No further pages (reached the newest).")
            break

        current_page, raw_bytes = fetch_json(prev_url, delay=delay)
        if current_page is None:
            print("  Could not load next page; stopping.")
            break
        pages_visited += 1
        current_url = prev_url

    print("\n" + "=" * 60)
    print("Crawl complete.")
    print(f"  Pages visited : {pages_visited}")
    print(f"  Pages {'queued' if dry_run else 'saved'}   : {pages_saved}")
    print(f"  Pages skipped : {pages_skipped}")


def main():
    parser = argparse.ArgumentParser(
        description="Save LCNAF feed pages containing items published on target date(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start-url",
        default="http://id.loc.gov/authorities/names/activitystreams/feed/1",
        help="Feed page to begin seeking from (default: feed/1, the most recent).",
    )
    parser.add_argument(
        "--output-dir",
        default="./feeds",
        help="Directory to save matching feed files (default: ./feeds).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=10.0,
        help="Seconds to pause between requests (default: 10).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching pages without saving files.",
    )
    parser.add_argument(
        "--date",
        dest="date",
        metavar="YYYY-MM-DD",
        type=validate_date,
        help="Single date to look for (YYYY-MM-DD). Defaults to today if no date flags given.",
    )
    parser.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        type=validate_date,
        help="Newest date of a range (YYYY-MM-DD). Use with --end-date.",
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        type=validate_date,
        help="Oldest date of a range (YYYY-MM-DD, inclusive). Use with --start-date.",
    )
    args = parser.parse_args()

    # Build the set of target dates
    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end   = date.fromisoformat(args.end_date)
        # Accept either order — min/max handles it
        lo, hi = min(start, end), max(start, end)
        target_dates = {
            (lo + timedelta(days=i)).isoformat()
            for i in range((hi - lo).days + 1)
        }
    elif args.start_date or args.end_date:
        parser.error("--start-date and --end-date must be used together.")
    elif args.date:
        target_dates = {args.date}
    else:
        target_dates = {date.today().isoformat()}

    crawl(
        start_url=args.start_url,
        output_dir=args.output_dir,
        delay=args.delay,
        dry_run=args.dry_run,
        target_dates=target_dates,
    )


if __name__ == "__main__":
    main()
