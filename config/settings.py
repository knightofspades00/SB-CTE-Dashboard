"""
config/settings.py — Centralised configuration pulled from environment variables.
All tuneable values (API keys, database path, search parameters) live here;
defaults let the app run locally without a .env file.
"""

import os

class Config:
    """Flat configuration namespace read from environment variables at import time."""
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-default-change-me")
    # Debug is OFF by default — must be explicitly opted in by setting FLASK_ENV=development.
    # This prevents a misconfigured production server from running with the debugger exposed.
    DEBUG = os.environ.get("FLASK_ENV", "production") == "development"
    DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join("database", "cte_dashboard.db"))
    USAJOBS_USER_AGENT = os.environ.get("USAJOBS_USER_AGENT", "")
    USAJOBS_API_KEY    = os.environ.get("USAJOBS_API_KEY", "")
    USAJOBS_BASE_URL   = "https://data.usajobs.gov/api/search"
    JOB_SEARCH_LOCATION         = os.environ.get("JOB_SEARCH_LOCATION", "San Bernardino, CA")
    # Default radius covers the populated southwest of SB County AND the high desert
    # (Hesperia ~30 mi, Victorville ~40 mi, Apple Valley ~40 mi, Barstow ~75 mi).
    # The _is_sb_county() post-filter drops anything that falls inside the radius
    # but outside the county, so a wider radius does not leak Riverside/LA county jobs.
    JOB_SEARCH_RADIUS           = int(os.environ.get("JOB_SEARCH_RADIUS", 75))
    JOB_SEARCH_RESULTS_PER_PAGE = int(os.environ.get("JOB_SEARCH_RESULTS_PER_PAGE", 10))
    CACHE_REFRESH_HOURS = int(os.environ.get("CACHE_REFRESH_HOURS", 24))