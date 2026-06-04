"""
database/bootstrap.py — One-shot database initialiser for first-deploy boots.

On a fresh machine (Render free tier, a new Docker container, a colleague's
laptop), the SQLite file doesn't exist yet. This script does the same work a
local developer does manually in the README "First-time setup" steps, all
inside a single command that's safe to re-run.

It:
  1. Creates the schema if cte_dashboard.db is missing or empty.
  2. Imports schools / pathways / careers from CTE_Connections.xlsx (when
     the spreadsheet is present in database/).
  3. Applies hardcoded SBCUSD school coordinates (so the map renders even
     without an outbound Nominatim call).
  4. Seeds the county catalog (10 programs, 42 positions, ladders, pathway
     → program mapping).
  5. Reads database/currently_hiring.json into current_postings if the file
     is present — typically committed by the GitHub Actions refresh.

Idempotent on re-run: every step is a no-op when the data already matches.
Safe to use as the build step of a hosted deployment.

Usage:
    python database/bootstrap.py            # full bootstrap, skip if DB exists
    python database/bootstrap.py --force    # rebuild even if DB exists
"""

import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config


def db_path():
    return os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)


def schema_is_initialised(path):
    """True if the file exists and contains our key tables."""
    if not os.path.exists(path):
        return False
    try:
        conn = sqlite3.connect(path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('schools','pathways','cte_programs','county_positions')"
        ).fetchall()
        conn.close()
        return len(rows) == 4
    except sqlite3.Error:
        return False


def schools_have_data(path):
    """True if the schools table has at least one row (proxy for 'data imported')."""
    try:
        conn = sqlite3.connect(path)
        n = conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
        conn.close()
        return n > 0
    except sqlite3.Error:
        return False


def bootstrap(force=False):
    """Run every setup step the first-time README walks the dev through."""
    path = db_path()
    print(f"[bootstrap] DB path: {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if force and os.path.exists(path):
        print("[bootstrap] --force given; removing existing DB")
        os.remove(path)

    # 1. Schema
    if schema_is_initialised(path):
        print("[bootstrap] Schema already present")
    else:
        print("[bootstrap] Creating schema ...")
        from database.init_db import init_db
        init_db()

    # 2. School / pathway / career import from xlsx (skip if data already loaded
    #    OR if xlsx is missing — fixtures-style bootstraps can omit it).
    if schools_have_data(path):
        print("[bootstrap] Schools data already present, skipping xlsx import")
    else:
        xlsx_path = os.path.join(PROJECT_ROOT, "database", "CTE_Connections.xlsx")
        if os.path.exists(xlsx_path):
            print(f"[bootstrap] Importing from {xlsx_path}")
            from database.import_data import run_import
            run_import(xlsx_path)
        else:
            print("[bootstrap] CTE_Connections.xlsx not present; skipping school import "
                  "(dashboard will run but with an empty schools table)")

    # 3. SBCUSD coordinate overrides (idempotent — only fills missing coords)
    print("[bootstrap] Applying SBCUSD coordinate overrides")
    from database.geocode_schools import apply_hardcoded_overrides
    apply_hardcoded_overrides()

    # 4. County catalog seed (idempotent — upserts on conflict)
    print("[bootstrap] Seeding county catalog ...")
    from database.import_county_data import run as run_county_import
    run_county_import()

    # 5. Live "Hiring now" overlay from committed JSON, if present
    hiring_json = os.path.join(PROJECT_ROOT, "database", "currently_hiring.json")
    if os.path.exists(hiring_json):
        print(f"[bootstrap] Loading {hiring_json} into current_postings")
        from services.refresh_postings import run as run_refresh
        run_refresh(prefer_live=False)
    else:
        print("[bootstrap] No currently_hiring.json — overlay will be empty until "
              "next refresh run")

    print("[bootstrap] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true",
                        help="Delete the existing DB and start fresh.")
    args = parser.parse_args()
    bootstrap(force=args.force)
