"""
routes/programs.py — REST + HTML endpoints for the 10 county CTE programs.

JSON:
  /api/programs                         List all 10 programs with position counts
  /api/programs/<id>                    One program + positions + tied pathways
  /api/refresh-status                   "Hiring now" overlay freshness + counts

HTML:
  /programs                             Server-rendered browse page covering all
                                        10 programs with position cards, MQs,
                                        ladders, and live "Hiring now" pills.
                                        Anchor links per program for sharing.
"""

import re
import sqlite3

from flask import Blueprint, jsonify, current_app, render_template

from database.connection import get_db

programs_bp = Blueprint("programs", __name__)


def _slugify(name):
    """Lowercase + dash + a–z0–9 only — used for stable anchor IDs."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


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


@programs_bp.route("/api/refresh-status", methods=["GET"])
def get_refresh_status():
    """Return freshness of the "Hiring now" overlay + match counts per program."""
    conn = get_db()
    try:
        summary = conn.execute(
            """
            SELECT COUNT(*)                                 AS total_postings,
                   COUNT(DISTINCT position_id)              AS positions_hiring,
                   MAX(fetched_at)                          AS last_refresh
            FROM current_postings
            """
        ).fetchone()
        per_program = conn.execute(
            """
            SELECT p.id, p.name, COUNT(cp_post.id) AS posting_count
            FROM cte_programs p
            LEFT JOIN county_positions cp     ON cp.cte_program_id = p.id
            LEFT JOIN current_postings cp_post ON cp_post.position_id = cp.id
            GROUP BY p.id
            ORDER BY p.display_order, p.name
            """
        ).fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_refresh_status: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()
    return jsonify({
        "total_postings":   summary["total_postings"] or 0,
        "positions_hiring": summary["positions_hiring"] or 0,
        "last_refresh":     summary["last_refresh"],
        "per_program":      [dict(r) for r in per_program],
    })


@programs_bp.route("/programs", methods=["GET"])
def render_programs_page():
    """
    Render a single page listing all 10 county CTE programs and their positions.

    Each program is a section with an anchor link (#<slug>) so counselors can
    share a deep link to a specific program. Positions render with the same
    MQ text, pay band, career ladder, and "Hiring now" pill as the SPA.
    """
    conn = get_db()
    try:
        program_rows = conn.execute(
            """
            SELECT p.id, p.name, p.description, p.display_order,
                   COUNT(DISTINCT cp.id)         AS position_count,
                   COUNT(DISTINCT cp_post.id)    AS posting_count
            FROM cte_programs p
            LEFT JOIN county_positions cp ON cp.cte_program_id = p.id
            LEFT JOIN current_postings cp_post ON cp_post.position_id = cp.id
            GROUP BY p.id
            ORDER BY p.display_order, p.name
            """
        ).fetchall()
        positions_by_program = {}
        for prog in program_rows:
            rows = conn.execute(
                """
                SELECT id, job_code, title, union_code, grade,
                       min_hourly, max_hourly, mqs_text, notes, apply_url
                FROM county_positions
                WHERE cte_program_id = ?
                ORDER BY (job_code = 'NEW'), title
                """,
                (prog["id"],),
            ).fetchall()
            positions_by_program[prog["id"]] = [dict(r) for r in rows]

        # Bulk-fetch ladder steps and current postings, group in Python.
        position_ids = [p["id"] for plist in positions_by_program.values() for p in plist]
        ladder_by_pos = {pid: [] for pid in position_ids}
        postings_by_pos = {pid: [] for pid in position_ids}
        if position_ids:
            qmarks = ",".join("?" * len(position_ids))
            for r in conn.execute(
                f"""
                SELECT entry_position_id, step_number, title, job_code
                FROM position_ladder_steps
                WHERE entry_position_id IN ({qmarks})
                ORDER BY entry_position_id, step_number
                """,
                position_ids,
            ).fetchall():
                ladder_by_pos[r["entry_position_id"]].append({
                    "step":     r["step_number"],
                    "title":    r["title"],
                    "job_code": r["job_code"],
                })
            for r in conn.execute(
                f"""
                SELECT position_id, posting_title, posting_url, posting_close_date
                FROM current_postings
                WHERE position_id IN ({qmarks})
                ORDER BY position_id, posting_title
                """,
                position_ids,
            ).fetchall():
                postings_by_pos[r["position_id"]].append({
                    "title":  r["posting_title"],
                    "url":    r["posting_url"],
                    "closes": r["posting_close_date"],
                })

        summary = conn.execute(
            "SELECT MAX(fetched_at) AS last_refresh FROM current_postings"
        ).fetchone()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in render_programs_page: {e}")
        return ("Database error", 500)
    finally:
        conn.close()

    # Decorate positions with ladder + posting data and compute salary string.
    programs = []
    for prog in program_rows:
        decorated_positions = []
        for p in positions_by_program[prog["id"]]:
            salary = None
            if p["min_hourly"] is not None and p["max_hourly"] is not None:
                salary = f"${p['min_hourly']:.2f} – ${p['max_hourly']:.2f} / hour"
            postings = postings_by_pos[p["id"]]
            ladder = [{"step": 1, "title": p["title"], "job_code": p["job_code"], "is_entry": True}]
            ladder += [{**s, "is_entry": False} for s in ladder_by_pos[p["id"]]]
            decorated_positions.append({
                **p,
                "salary":           salary,
                "ladder":           ladder,
                "current_postings": postings,
                "is_hiring_now":    bool(postings),
                "primary_apply_url": (postings[0]["url"] if postings else p["apply_url"]),
            })
        programs.append({
            "id":             prog["id"],
            "name":           prog["name"],
            "description":    prog["description"],
            "slug":           _slugify(prog["name"]),
            "position_count": prog["position_count"],
            "posting_count":  prog["posting_count"],
            "positions":      decorated_positions,
        })

    return render_template(
        "programs.html",
        programs=programs,
        last_refresh=summary["last_refresh"],
    )
