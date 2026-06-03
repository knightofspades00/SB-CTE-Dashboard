"""
database/init_db.py — One-time script to create the SQLite database schema.
Reads database/schema.sql and executes it against the configured database path.
Run before import_data.py when setting up a new environment.
"""

import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from config.settings import Config

def init_db():
    """Read schema.sql and apply it to the configured SQLite database, creating it if needed."""
    db_path     = os.path.join(PROJECT_ROOT, Config.DATABASE_PATH)
    schema_path = os.path.join(PROJECT_ROOT, "database", "schema.sql")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    print(f"Database path : {db_path}")
    print(f"Schema path   : {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print("✓ Database initialised.")
    except sqlite3.Error as e:
        print(f"✗ Database error: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
