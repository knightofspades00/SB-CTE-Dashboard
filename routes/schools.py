"""
routes/schools.py — REST endpoints for school data (/api/schools).
Exposes a list of all schools with pathway counts, and per-school pathway lookups.
"""

import sqlite3

from flask import Blueprint, jsonify, current_app

from database.connection import get_db

schools_bp = Blueprint("schools", __name__)

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

@schools_bp.route("/api/schools/full", methods=["GET"])
def get_schools_full():
    """Return every school enriched with its pathway IDs and county-program IDs.

    Single payload designed for the map frontend: the page loads this once at
    startup and filters in-memory as the student tweaks the filter chips
    (pathway, program, district). Faster and simpler than firing one request
    per filter combination.
    """
    conn = get_db()
    try:
        schools = conn.execute("""
            SELECT s.id, s.name, s.district, s.latitude, s.longitude
            FROM schools s
            ORDER BY s.district, s.name
        """).fetchall()
        pathway_rows = conn.execute("""
            SELECT sp.school_id, sp.pathway_id, p.cte_program_id
            FROM school_pathways sp
            JOIN pathways p ON sp.pathway_id = p.id
        """).fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_schools_full: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

    pathway_ids = {s["id"]: [] for s in schools}
    program_ids = {s["id"]: set() for s in schools}
    for r in pathway_rows:
        sid = r["school_id"]
        if sid not in pathway_ids:
            continue
        pathway_ids[sid].append(r["pathway_id"])
        if r["cte_program_id"] is not None:
            program_ids[sid].add(r["cte_program_id"])

    out = []
    for s in schools:
        d = dict(s)
        d["pathway_ids"] = pathway_ids[s["id"]]
        d["program_ids"] = sorted(program_ids[s["id"]])
        d["pathway_count"] = len(d["pathway_ids"])
        out.append(d)
    return jsonify(out)


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
