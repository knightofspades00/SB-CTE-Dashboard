"""
routes/pathways.py — REST endpoints for CTE pathway data (/api/pathways).
Provides pathway listings, detail views with linked schools and careers,
and a reverse-lookup to find pathways that lead to a given career.
"""

from flask import Blueprint, jsonify, current_app
import sqlite3
import os

pathways_bp = Blueprint("pathways", __name__)

def get_db():
    """Open and return a SQLite connection with Row factory enabled."""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        current_app.config["DATABASE_PATH"]
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@pathways_bp.route("/api/pathways", methods=["GET"])
def get_pathways():
    """Return all pathways ordered by sector, each with a count of schools that offer it."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT p.id, p.name, p.sector, p.department, p.description,
                   COUNT(DISTINCT sp.school_id) AS school_count
            FROM pathways p
            LEFT JOIN school_pathways sp ON p.id = sp.pathway_id
            GROUP BY p.id
            ORDER BY p.sector NULLS LAST, p.name
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_pathways: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@pathways_bp.route("/api/pathways/<int:pathway_id>", methods=["GET"])
def get_pathway_detail(pathway_id):
    """Return a pathway with its linked schools and career outcomes; 404 if not found."""
    conn = get_db()
    try:
        pathway = conn.execute("SELECT * FROM pathways WHERE id = ?", (pathway_id,)).fetchone()
        if not pathway:
            return jsonify({"error": "Pathway not found"}), 404
        schools = conn.execute("""
            SELECT s.id, s.name, s.district, s.latitude, s.longitude
            FROM schools s
            JOIN school_pathways sp ON s.id = sp.school_id
            WHERE sp.pathway_id = ?
            ORDER BY s.district, s.name
        """, (pathway_id,)).fetchall()
        careers = conn.execute("""
            SELECT c.id, c.name
            FROM careers c
            JOIN pathway_careers pc ON c.id = pc.career_id
            WHERE pc.pathway_id = ?
            ORDER BY c.name
        """, (pathway_id,)).fetchall()
        return jsonify({
            "pathway": dict(pathway),
            "schools": [dict(s) for s in schools],
            "careers": [dict(c) for c in careers]
        })
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_pathway_detail: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

@pathways_bp.route("/api/pathways/by-career/<int:career_id>", methods=["GET"])
def get_pathways_by_career(career_id):
    """Return all pathways that lead to a given career, each with its offering schools; 404 if the career doesn't exist."""
    conn = get_db()
    try:
        career = conn.execute("SELECT id, name FROM careers WHERE id = ?", (career_id,)).fetchone()
        if not career:
            return jsonify({"error": "Career not found"}), 404
        pathways = conn.execute("""
            SELECT p.id, p.name, p.sector, p.description
            FROM pathways p
            JOIN pathway_careers pc ON p.id = pc.pathway_id
            WHERE pc.career_id = ?
            ORDER BY p.sector NULLS LAST, p.name
        """, (career_id,)).fetchall()
        result = []
        for pw in pathways:
            schools = conn.execute("""
                SELECT s.id, s.name, s.district, s.latitude, s.longitude
                FROM schools s
                JOIN school_pathways sp ON s.id = sp.school_id
                WHERE sp.pathway_id = ?
                ORDER BY s.district, s.name
            """, (pw["id"],)).fetchall()
            result.append({**dict(pw), "schools": [dict(s) for s in schools]})
        return jsonify({"career": dict(career), "pathways": result})
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_pathways_by_career: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
