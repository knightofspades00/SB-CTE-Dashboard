"""
routes/careers.py — REST endpoint for career data (/api/careers).
Returns all careers with a count of the CTE pathways linked to each.
"""

from flask import Blueprint, jsonify, current_app
import sqlite3
import os

careers_bp = Blueprint("careers", __name__)

def get_db():
    """Open and return a SQLite connection with Row factory enabled."""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        current_app.config["DATABASE_PATH"]
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@careers_bp.route("/api/careers", methods=["GET"])
def get_careers():
    """Return all careers alphabetically, each with a count of linked pathways."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT c.id, c.name, COUNT(pc.pathway_id) AS pathway_count
            FROM careers c
            LEFT JOIN pathway_careers pc ON c.id = pc.career_id
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_careers: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
