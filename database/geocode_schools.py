"""
geocode_schools.py — One-time script to populate lat/lng for all 78 schools.
Uses Nominatim (OpenStreetMap) — completely free, no API key required.
Run once after import_data.py. Re-run any time new schools are added.

Terms of service: max 1 request per second — the sleep(1) below handles this.

Usage:
    python database/geocode_schools.py
"""

import os
import sys
import sqlite3
import time
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Identify our app to Nominatim — their terms require a descriptive User-Agent
HEADERS = {
    "User-Agent": "CTE-Job-Dashboard/1.0 (City of San Bernardino student portal)"
}

# Hardcoded coordinates for the 9 San Bernardino City Unified School District
# campuses. Nominatim is unreliable for these (many are nested inside city blocks
# and don't have their own OSM entry), so we apply these overrides up front and
# only fall back to Nominatim for anything not in this map. Coordinates verified
# against the SBCUSD prototype dashboard built by AniVation-Tech Academy.
SBCUSD_OVERRIDES = {
    "Arroyo Valley High School": (34.1188, -117.3287),
    "Cajon High School":          (34.1772, -117.3104),
    "Indian Springs High School": (34.1714, -117.2908),
    "Pacific High":               (34.1292, -117.2648),
    "San Andreas High":           (34.1295, -117.2156),
    "San Bernardino High School": (34.1314, -117.2964),
    "San Gorgonio High School":   (34.1260, -117.2372),
    "Sierra High School":         (34.0875, -117.2489),
    # Virtual Academy is online-only; pin to SBCUSD district HQ for the map.
    "Virtual Academy":            (34.1083, -117.2934),
}


def apply_hardcoded_overrides():
    """Set coords for every school in SBCUSD_OVERRIDES that lacks them in the DB."""
    conn = get_connection()
    try:
        updated = 0
        for name, (lat, lng) in SBCUSD_OVERRIDES.items():
            row = conn.execute(
                "SELECT id FROM schools WHERE name = ? AND (latitude IS NULL OR longitude IS NULL)",
                (name,)
            ).fetchone()
            if not row:
                continue
            conn.execute(
                "UPDATE schools SET latitude = ?, longitude = ? WHERE id = ?",
                (lat, lng, row["id"])
            )
            updated += 1
        conn.commit()
        if updated:
            print(f"  Applied {updated} hardcoded SBCUSD coordinate override(s).")
    finally:
        conn.close()

def geocode_school(school_name, district, api_key=None):
    """
    Try progressively broader queries until we get a result.
    Most schools will match on the first try. A few need a broader search.
    """
    queries = [
        f"{school_name}, {district}, San Bernardino County, CA",
        f"{school_name}, San Bernardino County, CA",
        f"{school_name}, San Bernardino, CA",
        f"{school_name}, CA",
    ]

    for query in queries:
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={
                    "q":              query,
                    "format":         "json",
                    "limit":          1,
                    "countrycodes":   "us",
                    "addressdetails": 0,
                },
                headers=HEADERS,
                timeout=10
            )
            results = response.json()
            if results:
                lat = float(results[0]["lat"])
                lng = float(results[0]["lon"])
                return lat, lng, query  # return the query that worked
        except Exception as e:
            print(f"    Request error: {e}")

        # Respect Nominatim rate limit between retries too
        time.sleep(1)

    return None, None, None

def run_geocoding():
    """
    Geocode every school that lacks coordinates by querying Nominatim with progressively broader
    queries until a result is found.  Updates the database row immediately after each success.
    Prints a list of schools that need manual coordinates at the end.

    SBCUSD schools are seeded from the hardcoded override table first so we don't waste
    Nominatim quota on campuses we already know.
    """
    apply_hardcoded_overrides()
    conn = get_connection()
    try:
        schools = conn.execute("""
            SELECT id, name, district
            FROM schools
            WHERE latitude IS NULL OR longitude IS NULL
            ORDER BY district, name
        """).fetchall()

        if not schools:
            print("✓ All schools already have coordinates. Nothing to do.")
            return

        print(f"Geocoding {len(schools)} schools using Nominatim (OpenStreetMap)...")
        print(f"This will take approximately {len(schools)} seconds.\n")

        success = 0
        failed  = []

        for school in schools:
            print(f"  [{school['id']}] {school['name']}")

            lat, lng, matched_query = geocode_school(
                school["name"],
                school["district"]
            )

            if lat and lng:
                conn.execute(
                    "UPDATE schools SET latitude = ?, longitude = ? WHERE id = ?",
                    (lat, lng, school["id"])
                )
                conn.commit()
                print(f"       ✓ {lat:.6f}, {lng:.6f}")
                success += 1
            else:
                print(f"       ✗ Could not geocode — will need manual entry")
                failed.append(school["name"])

            # Required by Nominatim terms of service — 1 request per second max
            time.sleep(1)

        print(f"\n{'='*50}")
        print(f"✓ Done. {success} succeeded, {len(failed)} failed.")

        if failed:
            print(f"\nSchools that need manual coordinates:")
            for name in failed:
                print(f"  - {name}")
            print(f"\nTo fix manually, run this for each failed school:")
            print(f"  python database/geocode_schools.py --manual \"School Name\" 34.000000 -117.000000")

    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)
    finally:
        conn.close()

def get_connection():
    """Open and return a SQLite connection with Row factory enabled."""
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def set_manual(school_name, lat, lng):
    """Manually set coordinates for a school that Nominatim couldn't find."""
    conn = get_connection()
    try:
        result = conn.execute(
            "SELECT id FROM schools WHERE name = ?", (school_name,)
        ).fetchone()
        if not result:
            print(f"✗ School not found: {school_name}")
            sys.exit(1)
        conn.execute(
            "UPDATE schools SET latitude = ?, longitude = ? WHERE id = ?",
            (lat, lng, result["id"])
        )
        conn.commit()
        print(f"✓ Coordinates set for '{school_name}': {lat}, {lng}")
    finally:
        conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", nargs=3,
                        metavar=("SCHOOL_NAME", "LAT", "LNG"),
                        help="Manually set coordinates for one school")
    args = parser.parse_args()

    if args.manual:
        set_manual(args.manual[0], float(args.manual[1]), float(args.manual[2]))
    else:
        run_geocoding()