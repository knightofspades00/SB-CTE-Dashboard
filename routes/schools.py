"""
routes/schools.py — REST endpoints for school data (/api/schools).
Exposes a list of all schools with pathway counts, and per-school pathway lookups.
"""

from flask import Blueprint, jsonify, current_app
import sqlite3
import os

schools_bp = Blueprint("schools", __name__)

def get_db():
    """Open and return a SQLite connection with Row factory enabled."""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        current_app.config["DATABASE_PATH"]
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@schools_bp.route("/api/schools", methods=["GET"])
def get_schools():
    """Return all schools ordered by district and name, each with a count of offered pathways."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT s.id, s.name, s.district, s.latitude, s.longitude,
                   COUNT(sp.pathway_id) AS pathway_count
            FROM schools s
            LEFT JOIN school_pathways sp ON s.id = sp.school_id
            GROUP BY s.id
            ORDER BY s.district, s.name
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_schools: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@schools_bp.route("/api/schools/<int:school_id>/pathways", methods=["GET"])
def get_school_pathways(school_id):
    """Return a school's metadata and its list of offered pathways; 404 if the school doesn't exist."""
    conn = get_db()
    try:
        school = conn.execute(
            "SELECT id, name, district FROM schools WHERE id = ?", (school_id,)
        ).fetchone()
        if not school:
            return jsonify({"error": "School not found"}), 404
        pathways = conn.execute("""
            SELECT p.id, p.name, p.sector, p.description
            FROM pathways p
            JOIN school_pathways sp ON p.id = sp.pathway_id
            WHERE sp.school_id = ?
            ORDER BY p.sector, p.name
        """, (school_id,)).fetchall()
        return jsonify({"school": dict(school), "pathways": [dict(p) for p in pathways]})
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_school_pathways: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
