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

def fetch_live_postings(timeout_ms=30000, max_pages=30):
    """Render the NeoGov portal in headless Chromium and extract every open posting.

    NeoGov renders the listings via Knockout.js on the client. We let the page
    settle, harvest the visible job rows, then either advance via the Next
    button or bump the URL's ?page=N parameter until we run out of pages.

    Returns a list of {"title", "url", "closes"} dicts. Returns None if
    Playwright is not installed; logs and returns [] on a runtime failure so
    the caller can fall through to the JSON override.

    Catalogue of relevant DOM (as of 2026-06):
      <li class="list-item" data-job-id="5314703">
        <h3 class="job-item-link-container">
          <a class="item-details-link"
             href="/careers/sanbernardino/jobs/5314703/animal-keeper-i">
            Animal Keeper I
          </a>
        </h3>
        <ul class="list-meta">
          <li>Location ...</li><li>Full-time ...</li>
          ...
          <li>Continuous</li>  <!-- or a specific closing date -->
        </ul>
      </li>
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
    seen_ids = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (SBC CTE Dashboard refresh; +internal)"
            )
            page = context.new_page()
            logger.info(f"Loading {PORTAL_URL} ...")
            page.goto(PORTAL_URL, wait_until="networkidle", timeout=timeout_ms)

            page_num = 1
            while page_num <= max_pages:
                page.wait_for_timeout(2000)  # let knockout bindings settle
                # Wait until at least one job row is in the DOM before reading.
                try:
                    page.wait_for_selector("li[data-job-id]", timeout=8000)
                except Exception:
                    logger.warning(f"  page {page_num}: no job rows rendered")
                    break

                rows = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('li[data-job-id]')).map(row => {
                        const a = row.querySelector('h3 a.item-details-link, h3 a');
                        const metaLis = Array.from(row.querySelectorAll('ul.list-meta li'))
                            .map(li => (li.innerText || '').trim());
                        return {
                            jobId: row.getAttribute('data-job-id'),
                            title: a ? (a.innerText || '').trim() : '',
                            href:  a ? a.getAttribute('href') : '',
                            meta:  metaLis,
                        };
                    });
                }""")
                if not rows:
                    break

                new_on_this_page = 0
                for r in rows:
                    jid = r.get("jobId")
                    if not jid or jid in seen_ids:
                        continue
                    seen_ids.add(jid)
                    title = (r.get("title") or "").strip()
                    href = (r.get("href") or "").strip()
                    if not title or not href:
                        continue
                    url = (href if href.startswith("http")
                           else f"https://www.governmentjobs.com{href}")
                    # Close date: NeoGov puts it in one of the .list-meta <li>s.
                    # It's usually "Continuous" or "MM/DD/YYYY ...".
                    closes = ""
                    for m in r.get("meta", []):
                        if m.lower() == "continuous" or any(c.isdigit() for c in m[:10]):
                            if "/" in m[:10] or m.lower() == "continuous":
                                closes = m
                                break
                    postings.append({"title": title, "url": url, "closes": closes})
                    new_on_this_page += 1

                logger.info(f"  page {page_num}: {new_on_this_page} new postings, {len(postings)} total")
                if new_on_this_page == 0:
                    break

                # Advance: prefer clicking Next; otherwise bump ?page= param.
                next_btn = page.locator("a[aria-label='Go to next page'], a.next, a[aria-label='Next']")
                advanced = False
                if next_btn.count():
                    cls = (next_btn.first.get_attribute("class") or "")
                    if "disabled" not in cls.lower():
                        try:
                            next_btn.first.click()
                            advanced = True
                        except Exception:
                            pass
                if not advanced:
                    page_num += 1
                    nav_url = f"{PORTAL_URL}?page={page_num}"
                    try:
                        page.goto(nav_url, wait_until="networkidle", timeout=timeout_ms)
                        advanced = True
                    except Exception as e:
                        logger.warning(f"  could not load page {page_num}: {e}")
                        break
                else:
                    page_num += 1
        finally:
            browser.close()

    logger.info(f"Scraped {len(postings)} unique postings from NeoGov "
                f"({len(seen_ids)} job-ids seen)")
    return postings


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
    """For each posting, find the best matching county_position by title prefix.

    A posting matches a position when the position's normalised token sequence
    is a PREFIX of the posting's normalised tokens. So:
      catalog "Animal Keeper I"      matches posting "Animal Keeper I (Wildlife)"  ✓
      catalog "Office Assistant"     matches posting "Office Assistant - Probation" ✓
      catalog "Equipment Operator"   does NOT match "Senior Equipment Operator"    ✗
      catalog "Equipment Operator"   does NOT match "Seasonal Equipment Operator"  ✗

    The strict-prefix rule keeps higher-rung postings (Senior X, Lead X) from
    masquerading as entry-level openings — those rungs may eventually become
    their own catalog rows when we track them, but for now Hiring-now only
    surfaces matches at the entry level.

    Returns a list of {position_id, posting_title, posting_url, posting_close_date} dicts.
    """
    positions = conn.execute(
        "SELECT id, title FROM county_positions"
    ).fetchall()
    # Sort by descending token-length so the most specific catalog title wins
    # (e.g. "Office Assistant - Healthcare" beats plain "Office Assistant").
    indexed = sorted(
        [(p["id"], p["title"], _normalise(p["title"])) for p in positions],
        key=lambda x: -len(x[2]),
    )

    matched = []
    skipped_higher_rung = 0
    for posting in postings:
        post_tokens = _normalise(posting["title"])
        if not post_tokens:
            continue
        best = None
        for pid, ptitle, ptokens in indexed:
            if not ptokens:
                continue
            n = len(ptokens)
            if len(post_tokens) >= n and post_tokens[:n] == ptokens:
                best = (pid, ptitle)
                break
        if best:
            matched.append({
                "position_id":        best[0],
                "posting_title":      posting["title"],
                "posting_url":        posting["url"],
                "posting_close_date": posting.get("closes") or None,
            })
            logger.debug(f"  matched: {posting['title']!r} -> {best[1]!r}")
        else:
            # Heuristic flag: if the posting starts with a known higher-rung
            # modifier, count it for diagnostics (it's intentionally unmatched).
            if post_tokens and post_tokens[0] in {"senior", "lead", "supervising",
                                                   "assistant", "deputy", "chief"}:
                skipped_higher_rung += 1
    logger.info(
        f"Matched {len(matched)} of {len(postings)} postings to catalog positions "
        f"({skipped_higher_rung} higher-rung postings intentionally skipped)"
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
