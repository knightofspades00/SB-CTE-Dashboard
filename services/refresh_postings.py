"""
services/refresh_postings.py — Daily refresh of the "currently hiring" overlay.

Wipes and rebuilds the current_postings table from one of two sources:

  1. Live scrape of governmentjobs.com/careers/sanbernardino (preferred).
     NeoGov renders the listing entirely via client-side JavaScript, so this
     requires a headless browser. Playwright is used when installed; if it
     isn't, this mode is skipped without crashing.

  2. Manual override file at database/currently_hiring.json.
     A small JSON array the user can hand-edit when Playwright isn't
     available (or to seed test data). Shape:
         [
             {
                 "title":  "Office Assistant",
                 "url":    "https://www.governmentjobs.com/jobs/12345-1/...",
                 "closes": "2026-06-30"
             },
             ...
         ]

Whichever source is used, each posting is title-matched against
county_positions (normalised, case-insensitive, substring tolerant) and
inserted into current_postings. The route layer then exposes the postings
under each position so the frontend can show a "Hiring now" pill.

Usage:
    python services/refresh_postings.py           # auto-pick source
    python services/refresh_postings.py --json    # force JSON-only mode
    python services/refresh_postings.py --print   # print matches, don't write

Schedule daily via Windows Task Scheduler or cron — see README.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config

PORTAL_URL = "https://www.governmentjobs.com/careers/sanbernardino"
OVERRIDE_PATH = os.path.join(PROJECT_ROOT, "database", "currently_hiring.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [refresh_postings] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source 1: Live scrape via Playwright
# ---------------------------------------------------------------------------

def fetch_live_postings(timeout_ms=20000):
    """Render the NeoGov portal in headless Chromium and extract every open posting.

    Returns a list of {"title", "url", "closes"} dicts. Returns None if Playwright
    is not installed; raises on any other error so the caller can log it.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning(
            "Playwright not installed — skipping live scrape. "
            "Run `pip install playwright && playwright install chromium` to enable."
        )
        return None

    postings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (SBC CTE Dashboard refresh; +internal)"
            )
            page = context.new_page()
            logger.info(f"Loading {PORTAL_URL} ...")
            page.goto(PORTAL_URL, wait_until="networkidle", timeout=timeout_ms)

            # The job list renders as a <table> of rows with class "job-table-title".
            # NeoGov sometimes paginates; click "next" until no more pages exist.
            seen_first_id = None
            while True:
                page.wait_for_timeout(800)  # let knockout bindings settle
                rows = page.locator("a.job-table-title").all()
                if not rows:
                    break

                # Detect a no-op next-click (same first row twice) to avoid infinite loops.
                first_href = rows[0].get_attribute("href") or ""
                if seen_first_id == first_href:
                    break
                seen_first_id = first_href

                for a in rows:
                    title = (a.inner_text() or "").strip()
                    href = a.get_attribute("href") or ""
                    if not title or not href:
                        continue
                    url = href if href.startswith("http") else f"https://www.governmentjobs.com{href}"
                    # Closing date is in a sibling cell — best-effort, may be empty.
                    closes = ""
                    try:
                        close_el = a.locator("xpath=ancestor::tr//td[contains(@class,'closing-date')]")
                        if close_el.count():
                            closes = (close_el.first.inner_text() or "").strip()
                    except Exception:
                        pass
                    postings.append({"title": title, "url": url, "closes": closes})

                # Advance pagination if a Next button is enabled.
                next_btn = page.locator("a[aria-label='Next']")
                if next_btn.count() == 0:
                    break
                cls = (next_btn.first.get_attribute("class") or "")
                if "disabled" in cls:
                    break
                next_btn.first.click()
        finally:
            browser.close()

    # De-duplicate by URL (NeoGov sometimes lists the same posting twice).
    seen = set()
    deduped = []
    for p in postings:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        deduped.append(p)
    logger.info(f"Scraped {len(deduped)} unique postings from NeoGov")
    return deduped


# ---------------------------------------------------------------------------
# Source 2: Manual JSON override
# ---------------------------------------------------------------------------

def fetch_override_postings():
    """Read database/currently_hiring.json if it exists; return list or empty list."""
    if not os.path.exists(OVERRIDE_PATH):
        logger.info(f"No override file at {OVERRIDE_PATH}")
        return []
    try:
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Could not read override file: {e}")
        return []
    if not isinstance(data, list):
        logger.error("Override JSON must be a list of posting objects")
        return []
    out = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = (entry.get("title") or "").strip()
        url = (entry.get("url") or "").strip()
        if not title or not url:
            continue
        out.append({"title": title, "url": url, "closes": entry.get("closes", "")})
    logger.info(f"Loaded {len(out)} postings from override file")
    return out


# ---------------------------------------------------------------------------
# Title matching against the catalog
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")

def _normalise(title):
    """Lowercase, collapse to a tuple of word tokens for matching."""
    return tuple(_TOKEN_RE.findall((title or "").lower()))


def match_postings_to_positions(conn, postings):
    """For each posting, find the best matching county_position by title overlap.

    A posting matches a position when the position's normalised token sequence
    appears contiguously inside the posting's normalised tokens (so e.g.
    "Office Assistant I" matches the catalog's "Office Assistant"). Returns a
    list of {position_id, posting_title, posting_url, posting_close_date} dicts.
    """
    positions = conn.execute(
        "SELECT id, title FROM county_positions"
    ).fetchall()
    # Sort positions by descending token-length so multi-word matches win first
    # (e.g. "Office Assistant - Healthcare" beats "Office Assistant" when both apply).
    indexed = sorted(
        [(p["id"], p["title"], _normalise(p["title"])) for p in positions],
        key=lambda x: -len(x[2]),
    )

    matched = []
    for posting in postings:
        post_tokens = _normalise(posting["title"])
        if not post_tokens:
            continue
        best = None
        for pid, ptitle, ptokens in indexed:
            if not ptokens:
                continue
            # Substring match: every token of the catalog title appears, in order,
            # somewhere in the posting title.
            n = len(ptokens)
            for i in range(len(post_tokens) - n + 1):
                if post_tokens[i:i + n] == ptokens:
                    best = (pid, ptitle)
                    break
            if best:
                break
        if best:
            matched.append({
                "position_id":        best[0],
                "posting_title":      posting["title"],
                "posting_url":        posting["url"],
                "posting_close_date": posting.get("closes") or None,
            })
            logger.debug(f"  matched: {posting['title']!r} -> {best[1]!r}")
    logger.info(
        f"Matched {len(matched)} of {len(postings)} postings to catalog positions"
    )
    return matched


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def _connect():
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def write_matches(conn, matches):
    """Wipe current_postings and insert the new match set in a single transaction."""
    conn.execute("DELETE FROM current_postings")
    for m in matches:
        conn.execute("""
            INSERT INTO current_postings
              (position_id, posting_title, posting_url, posting_close_date)
            VALUES (?, ?, ?, ?)
        """, (m["position_id"], m["posting_title"], m["posting_url"], m["posting_close_date"]))
    conn.commit()
    logger.info(f"current_postings now has {len(matches)} rows")


def run(prefer_live=True, print_only=False):
    """End-to-end refresh. Tries live first (if enabled), falls back to override file."""
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    if not os.path.exists(db_path):
        logger.error("Database not found. Run python database/init_db.py first.")
        sys.exit(1)

    postings = None
    if prefer_live:
        try:
            postings = fetch_live_postings()
        except Exception as e:
            logger.error(f"Live scrape failed: {e}")
            postings = None
    if postings is None:
        postings = fetch_override_postings()

    if not postings:
        logger.warning("No postings from any source — current_postings will be cleared.")
        postings = []

    conn = _connect()
    try:
        matches = match_postings_to_positions(conn, postings)
        if print_only:
            for m in matches:
                print(f"  -> position {m['position_id']}: {m['posting_title']} ({m['posting_url']})")
            return
        write_matches(conn, matches)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="Skip the live scrape and use only the override JSON file.",
    )
    parser.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Show what would be written without modifying the database.",
    )
    args = parser.parse_args()
    run(prefer_live=not args.json, print_only=args.print_only)
