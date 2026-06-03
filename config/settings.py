"""
config/settings.py — Centralised configuration pulled from environment variables.
The dashboard is backed by a curated county catalog (see database/import_county_data.py),
not a live external API, so configuration is intentionally minimal.
"""

import os

class Config:
    """Flat configuration namespace read from environment variables at import time."""
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-default-change-me")
    # Debug is OFF by default — must be explicitly opted in by setting FLASK_ENV=development.
    # This prevents a misconfigured production server from running with the debugger exposed.
    DEBUG = os.environ.get("FLASK_ENV", "production") == "development"
    DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join("database", "cte_dashboard.db"))