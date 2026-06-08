#!/usr/bin/env python3
"""
LCNAF Activity Stream Crawler
==============================
Crawls paginated JSON-LD activity stream feeds and downloads the object URLs
for items whose "published" date is within the last N days (default: 10 days,
i.e. NOT 11 or more days before today).

Usage
-----
    python3 lcnaf_crawler.py [options]

Options
-------
    --start-url URL         First feed page URL to begin crawling.
                            Default: http://id.loc.gov/authorities/names/activitystreams/feed/1
    --output-dir DIR        Directory to save downloaded files (default: ./downloads)
    --days INT              Skip items published more than this many days ago (default: 10,
                            which means items 11+ days old are excluded)
    --media-type TYPE       Only download links matching this mediaType.
                            Default: application/json
                            Common values:
                              application/rdf+xml
                              application/json
                              application/marc+xml
                              application/mads+xml
                              text/plain
    --direction             Crawl direction: "forward" (next) or "backward" (prev).
                            Default: forward
    --dry-run               Print what would be downloaded without saving files.
    --limit INT             Stop after downloading this many files (0 = unlimited).
    --delay FLOAT           Seconds to wait between HTTP requests (default: 0.5).

Examples
--------
    # Download JSON records updated in the last 10 days
    python3 lcnaf_crawler.py --start-url http://id.loc.gov/authorities/names/activitystreams/feed/1

    # Dry run, RDF/XML format, last 7 days
    python3 lcnaf_crawler.py --days 7 --media-type application/rdf+xml --dry-run

    # Start from a specific page, crawl backward, limit to 200 files
    python3 lcnaf_crawler.py --start-url http://id.loc.gov/authorities/names/activitystreams/feed/97 \\
        --direction backward --limit 200
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(value: str) -> date | None:
    """Parse a YYYY-MM-DD string into a date object, return None on failure."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fetch_json(url: str, delay: float = 0.0) -> dict | None:
    """Fetch a URL and return parsed JSON, or None on error."""
    if delay:
        time.sleep(delay)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, Exception) as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}", file=sys.stderr)
        return None


def safe_filename(url: str) -> str:
    """Convert a URL to a safe local filename."""
    # Strip scheme and replace unsafe characters
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"[^\w.\-]", "_", name)
    return name[:200]  # cap length


def download_file(url: str, dest_path: str, delay: float = 0.0) -> bool:
    """Download url to dest_path. Returns True on success."""
    if delay:
        time.sleep(delay)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(content)
        return True
    except Exception as exc:
        print(f"  [WARN] Download failed for {url}: {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Core crawler
# ---------------------------------------------------------------------------

def crawl(
    start_url: str,
    cutoff_date: date,
    output_dir: str,
    media_type: str,
    direction: str,
    dry_run: bool,
    limit: int,
    delay: float,
) -> None:
    """
    Walk feed pages starting at start_url, stopping when all items on a page
    predate the cutoff_date or there are no more pages.
    """
    today = date.today()
    downloaded = 0
    skipped_old = 0
    skipped_no_url = 0
    pages_visited = 0
    stop_crawling = False

    current_url = start_url

    print(f"Today's date      : {today}")
    print(f"Cutoff date       : {cutoff_date}  (items before this date are skipped)")
    print(f"Start URL         : {start_url}")
    print(f"Direction         : {direction}")
    print(f"Media type filter : {media_type}")
    print(f"Output directory  : {output_dir}")
    print(f"Dry run           : {dry_run}")
    print(f"Limit             : {limit if limit else 'unlimited'}")
    print("-" * 60)

    while current_url and not stop_crawling:
        print(f"\n[PAGE] {current_url}")
        page = fetch_json(current_url, delay=delay)
        if not page:
            print("  Could not load page; stopping.")
            break

        pages_visited += 1
        items = page.get("orderedItems", [])
        next_url = page.get("next") if direction == "forward" else page.get("prev")

        # Track whether every item on this page was too old
        all_old_on_page = True

        for item in items:
            published_str = item.get("published", "")
            pub_date = parse_date(published_str)

            if pub_date is None:
                print(f"  [SKIP] No valid published date: {published_str!r}")
                skipped_no_url += 1
                continue

            if pub_date < cutoff_date:
                skipped_old += 1
                # If crawling forward (oldest→newest) and we hit old items
                # we may still find newer items later, so keep going.
                # If crawling backward (newest→oldest) and all items are old,
                # stop early.
                if direction == "backward":
                    stop_crawling = True
                continue

            all_old_on_page = False  # at least one item is recent enough

            obj = item.get("object", {})
            obj_id = obj.get("id", "unknown")
            urls = obj.get("url", [])

            # Find the URL matching the requested media type
            target_href = None
            for link in urls:
                if isinstance(link, dict) and link.get("mediaType") == media_type:
                    target_href = link.get("href")
                    break

            if not target_href:
                print(f"  [SKIP] No {media_type} URL for {obj_id}")
                skipped_no_url += 1
                continue

            # Build destination path
            filename = safe_filename(target_href)
            dest = os.path.join(output_dir, filename)

            if dry_run:
                print(f"  [DRY RUN] Would download: {target_href}")
                print(f"            Published: {pub_date}  →  {dest}")
            else:
                print(f"  [GET] {target_href}  (published {pub_date})")
                ok = download_file(target_href, dest, delay=delay)
                if ok:
                    print(f"        → saved to {dest}")

            downloaded += 1
            if limit and downloaded >= limit:
                print(f"\nReached download limit ({limit}); stopping.")
                stop_crawling = True
                break

        # Optional early-exit: if crawling forward and every item was old,
        # later pages (which are even older) will also be old.
        if direction == "forward" and all_old_on_page and items:
            print("  [INFO] All items on this page predate the cutoff; stopping.")
            stop_crawling = True

        current_url = next_url if not stop_crawling else None

    # Summary
    print("\n" + "=" * 60)
    print("Crawl complete.")
    print(f"  Pages visited    : {pages_visited}")
    print(f"  Files {'queued' if dry_run else 'downloaded'}: {downloaded}")
    print(f"  Skipped (old)    : {skipped_old}")
    print(f"  Skipped (no URL) : {skipped_no_url}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl LCNAF activity stream feeds, downloading only recent items.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start-url",
        default="http://id.loc.gov/authorities/names/activitystreams/feed/1",
        help="Feed page URL to start from.",
    )
    parser.add_argument(
        "--output-dir",
        default="./downloads",
        help="Directory to save downloaded files.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=10,
        help=(
            "Maximum age (in days) of items to download. "
            "Items published more than this many days ago are skipped. "
            "Default 10 means items 11+ days old are excluded."
        ),
    )
    parser.add_argument(
        "--media-type",
        default="application/json",
        help="mediaType of the link to download per item.",
    )
    parser.add_argument(
        "--direction",
        choices=["forward", "backward"],
        default="forward",
        help="Crawl forward (via 'next') or backward (via 'prev').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be downloaded without saving anything.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after this many downloads (0 = unlimited).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to pause between HTTP requests (default: 0.5).",
    )
    args = parser.parse_args()

    today = date.today()
    cutoff = today - timedelta(days=args.days)

    crawl(
        start_url=args.start_url,
        cutoff_date=cutoff,
        output_dir=args.output_dir,
        media_type=args.media_type,
        direction=args.direction,
        dry_run=args.dry_run,
        limit=args.limit,
        delay=args.delay,
    )


if __name__ == "__main__":
    main()
