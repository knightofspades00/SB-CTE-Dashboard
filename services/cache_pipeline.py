"""
services/cache_pipeline.py — Background worker that pre-fetches job listings for every
pathway and writes them to the job_cache table.  Runs immediately on startup, then repeats
on the interval set by CACHE_REFRESH_HOURS (default 24 h).  Run as a standalone process:
    python services/cache_pipeline.py
"""

import os
import sys
import sqlite3
import logging
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config
from services.job_apis import search_usajobs
import schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cache_pipeline] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def get_connection():
    """Open and return a SQLite connection with foreign-key enforcement and Row factory enabled."""
    db_path = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def get_all_pathways():
    """Return every pathway as a list of dicts with keys id and name."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM pathways ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def refresh_cache():
    """
    Fetch live jobs for every pathway from USA Jobs and write them to job_cache.
    Clears old rows for a pathway before inserting fresh ones; rolls back on DB error.
    A 0.5 s sleep between pathways prevents hitting the USA Jobs rate limit.
    """
    logger.info("Starting job cache refresh...")
    if not Config.USAJOBS_USER_AGENT:
        logger.error("USAJOBS_USER_AGENT not set — cannot refresh cache.")
        return
    pathways      = get_all_pathways()
    success_count = 0
    error_count   = 0
    for pathway in pathways:
        pid    = pathway["id"]
        name   = pathway["name"]
        result = search_usajobs(
            keyword=name,
            location=Config.JOB_SEARCH_LOCATION,
            radius=Config.JOB_SEARCH_RADIUS,
            results_per_page=Config.JOB_SEARCH_RESULTS_PER_PAGE,
            page=1,
            user_agent=Config.USAJOBS_USER_AGENT,
            api_key=Config.USAJOBS_API_KEY,
        )
        if result["error"]:
            logger.warning(f"  x {name}: {result['error']}")
            error_count += 1
        else:
            conn = get_connection()
            try:
                conn.execute("DELETE FROM job_cache WHERE pathway_id = ?", (pid,))
                for job in result["jobs"]:
                    conn.execute("""
                        INSERT INTO job_cache (pathway_id, job_title, employer, location, apply_url)
                        VALUES (?, ?, ?, ?, ?)
                    """, (pid, job.get("title"), job.get("employer"), job.get("location"), job.get("apply_url")))
                conn.commit()
                logger.info(f"  + {name}: {len(result['jobs'])} jobs cached")
                success_count += 1
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"  x {name}: DB error - {e}")
                error_count += 1
            finally:
                conn.close()
        time.sleep(0.5)
    logger.info(f"Cache refresh complete. {success_count} succeeded, {error_count} failed.")

def start_scheduler():
    """Run refresh_cache immediately, then repeat it every CACHE_REFRESH_HOURS hours indefinitely."""
    hours = Config.CACHE_REFRESH_HOURS
    logger.info(f"Cache pipeline starting. Refresh every {hours} hour(s).")
    refresh_cache()
    schedule.every(hours).hours.do(refresh_cache)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    start_scheduler()
