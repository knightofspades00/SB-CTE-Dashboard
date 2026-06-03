"""
config/settings.py — Centralised configuration pulled from environment variables.
All tuneable values (API keys, database path, search parameters) live here;
defaults let the app run locally without a .env file.
"""

import os

class Config:
    """Flat configuration namespace read from environment variables at import time."""
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-default-change-me")
    DEBUG = os.environ.get("FLASK_ENV", "development") == "development"
    DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join("database", "cte_dashboard.db"))
    USAJOBS_USER_AGENT = os.environ.get("USAJOBS_USER_AGENT", "")
    USAJOBS_API_KEY    = os.environ.get("USAJOBS_API_KEY", "")
    USAJOBS_BASE_URL   = "https://data.usajobs.gov/api/search"
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    JOB_SEARCH_LOCATION         = os.environ.get("JOB_SEARCH_LOCATION", "San Bernardino, CA")
    JOB_SEARCH_RADIUS           = int(os.environ.get("JOB_SEARCH_RADIUS", 25))
    JOB_SEARCH_RESULTS_PER_PAGE = int(os.environ.get("JOB_SEARCH_RESULTS_PER_PAGE", 10))
    CACHE_REFRESH_HOURS = int(os.environ.get("CACHE_REFRESH_HOURS", 24))
    JSEARCH_API_KEY = os.environ.get("JSEARCH_API_KEY", "")