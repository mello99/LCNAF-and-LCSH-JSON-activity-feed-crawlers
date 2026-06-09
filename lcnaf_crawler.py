#!/usr/bin/env python3
"""
LCNAF Activity Stream Feed Crawler
====================================
Crawls paginated JSON-LD activity stream feed pages and saves any page
that contains at least one item with "published" equal to today's date.

The entire feed page (JSON-LD file) is saved — not the individual records
within it. A separate script handles processing those records.

Usage
-----
    python3 lcnaf_crawler.py [options]

Options
-------
    --start-url URL     Feed page URL to begin crawling.
                        Default: http://id.loc.gov/authorities/names/activitystreams/feed/1
    --output-dir DIR    Directory to save feed files (default: ./feeds)
    --direction STR     Crawl direction: "forward" (follow 'next') or
                        "backward" (follow 'prev'). Default: forward
    --delay FLOAT       Seconds to wait between requests (default: 10)
    --dry-run           Print matching pages without saving them

Examples
--------
    # Download all feed pages that contain today's records
    python3 lcnaf_crawler.py

    # Start from the most recent page and work backward
    python3 lcnaf_crawler.py \\
        --start-url http://id.loc.gov/authorities/names/activitystreams/feed/123439 \\
        --direction backward

    # Dry run to preview matches
    python3 lcnaf_crawler.py --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date


def fetch_json(url: str, delay: float = 0.0) -> dict | None:
    """Fetch a URL and return parsed JSON, or None on error."""
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


def safe_filename(url: str) -> str:
    """Convert a feed URL to a safe local filename, preserving the page number."""
    # e.g. http://id.loc.gov/authorities/names/activitystreams/feed/97  -> feed_97.json
    m = re.search(r"/feed/(\d+)$", url)
    if m:
        return f"feed_{m.group(1)}.json"
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200] + ".json"


def crawl(
    start_url: str,
    output_dir: str,
    direction: str,
    delay: float,
    dry_run: bool,
) -> None:
    today_str = date.today().isoformat()   # "YYYY-MM-DD"
    current_url = start_url
    pages_visited = 0
    pages_saved = 0
    pages_no_match = 0

    print(f"Today's date  : {today_str}")
    print(f"Start URL     : {start_url}")
    print(f"Direction     : {direction}")
    print(f"Output dir    : {output_dir}")
    print(f"Dry run       : {dry_run}")
    print("-" * 60)

    while current_url:
        print(f"\n[PAGE] {current_url}")
        page, raw_bytes = fetch_json(current_url, delay=delay)
        if page is None:
            print("  Could not load page; stopping.")
            break

        pages_visited += 1
        items = page.get("orderedItems", [])
        next_url = page.get("next") if direction == "forward" else page.get("prev")

        # Check if any item on this page was published today
        dates_on_page = {item.get("published", "") for item in items}
        has_today = today_str in dates_on_page

        if has_today:
            filename = safe_filename(current_url)
            dest = os.path.join(output_dir, filename)
            if dry_run:
                print(f"  [DRY RUN] Would save: {dest}")
            else:
                os.makedirs(output_dir, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(raw_bytes)
                print(f"  [SAVED] {dest}")
            pages_saved += 1
        else:
            other_dates = sorted(d for d in dates_on_page if d)
            print(f"  [SKIP] No items published today. Dates on page: {other_dates}")
            pages_no_match += 1

        current_url = next_url

    print("\n" + "=" * 60)
    print("Crawl complete.")
    print(f"  Pages visited : {pages_visited}")
    print(f"  Pages {'queued' if dry_run else 'saved'}   : {pages_saved}")
    print(f"  Pages skipped : {pages_no_match}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save LCNAF feed pages that contain items published today.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start-url",
        default="http://id.loc.gov/authorities/names/activitystreams/feed/1",
        help="Feed page URL to start from.",
    )
    parser.add_argument(
        "--output-dir",
        default="./feeds",
        help="Directory to save matching feed files.",
    )
    parser.add_argument(
        "--direction",
        choices=["forward", "backward"],
        default="forward",
        help="Follow 'next' links (forward) or 'prev' links (backward).",
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
    args = parser.parse_args()

    crawl(
        start_url=args.start_url,
        output_dir=args.output_dir,
        direction=args.direction,
        delay=args.delay,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
