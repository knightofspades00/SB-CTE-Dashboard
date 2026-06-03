"""
routes/programs.py — REST endpoints for the 10 county CTE programs (/api/programs).

These are the top-level career groupings the County of San Bernardino uses to
organise its entry-level classifications. Each program rolls up the school-side
pathways tied to it plus the county positions it employs.
"""

import sqlite3

from flask import Blueprint, jsonify, current_app

from database.connection import get_db

programs_bp = Blueprint("programs", __name__)


@programs_bp.route("/api/programs", methods=["GET"])
def list_programs():
    """List the 10 county CTE programs with a position count for each."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.display_order,
                   COUNT(cp.id) AS position_count
            FROM cte_programs p
            LEFT JOIN county_positions cp ON cp.cte_program_id = p.id
            GROUP BY p.id
            ORDER BY p.display_order, p.name
            """
        ).fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in list_programs: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


@programs_bp.route("/api/programs/<int:program_id>", methods=["GET"])
def get_program_detail(program_id):
    """Return program metadata, the positions it employs, and the pathways tied to it."""
    conn = get_db()
    try:
        program = conn.execute(
            "SELECT id, name, description, display_order FROM cte_programs WHERE id = ?",
            (program_id,),
        ).fetchone()
        if not program:
            return jsonify({"error": "Program not found"}), 404

        positions = conn.execute(
            """
            SELECT id, job_code, title, union_code, grade,
                   min_hourly, max_hourly, mqs_text, notes, apply_url
            FROM county_positions
            WHERE cte_program_id = ?
            ORDER BY (job_code = 'NEW'), title
            """,
            (program_id,),
        ).fetchall()

        pathways = conn.execute(
            """
            SELECT id, name, sector
            FROM pathways
            WHERE cte_program_id = ?
            ORDER BY sector NULLS LAST, name
            """,
            (program_id,),
        ).fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_program_detail: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

    return jsonify({
        "program":   dict(program),
        "positions": [dict(p) for p in positions],
        "pathways":  [dict(p) for p in pathways],
    })
