"""
routes/pathways.py — REST endpoints for CTE pathway data (/api/pathways).
Provides pathway listings, detail views with linked schools and careers,
and a reverse-lookup to find pathways that lead to a given career.
"""

import sqlite3

from flask import Blueprint, jsonify, current_app

from database.connection import get_db

pathways_bp = Blueprint("pathways", __name__)

@pathways_bp.route("/api/pathways", methods=["GET"])
def get_pathways():
    """Return all pathways ordered by sector, each with a count of schools that offer it."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT p.id, p.name, p.sector, p.department, p.description,
                   p.cte_program_id,
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
        rows = conn.execute("""
            SELECT p.id          AS pathway_id,
                   p.name        AS pathway_name,
                   p.sector      AS pathway_sector,
                   p.description AS pathway_description,
                   s.id          AS school_id,
                   s.name        AS school_name,
                   s.district    AS school_district,
                   s.latitude    AS school_latitude,
                   s.longitude   AS school_longitude
            FROM pathways p
            JOIN pathway_careers pc ON p.id = pc.pathway_id
            LEFT JOIN school_pathways sp ON p.id = sp.pathway_id
            LEFT JOIN schools s ON sp.school_id = s.id
            WHERE pc.career_id = ?
            ORDER BY p.sector NULLS LAST, p.name, s.district, s.name
        """, (career_id,)).fetchall()

        by_pathway = {}
        for r in rows:
            pid = r["pathway_id"]
            if pid not in by_pathway:
                by_pathway[pid] = {
                    "id":          pid,
                    "name":        r["pathway_name"],
                    "sector":      r["pathway_sector"],
                    "description": r["pathway_description"],
                    "schools":     [],
                }
            if r["school_id"] is not None:
                by_pathway[pid]["schools"].append({
                    "id":        r["school_id"],
                    "name":      r["school_name"],
                    "district":  r["school_district"],
                    "latitude":  r["school_latitude"],
                    "longitude": r["school_longitude"],
                })
        return jsonify({"career": dict(career), "pathways": list(by_pathway.values())})
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_pathways_by_career: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
