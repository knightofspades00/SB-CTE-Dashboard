"""
database/connection.py — Shared SQLite connection helper used by every route blueprint.
Centralises path resolution and row_factory configuration so the rest of the codebase
opens a properly-configured connection with a single import.
"""

import os
import sqlite3

from flask import current_app

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_db():
    """Open and return a SQLite connection with foreign keys on and Row factory enabled."""
    db_path = os.path.join(PROJECT_ROOT, current_app.config["DATABASE_PATH"])
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
