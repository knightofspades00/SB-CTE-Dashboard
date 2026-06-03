"""
routes/jobs.py — REST endpoints for the county-position catalog (/api/jobs, /api/positions).

The dashboard's job data is a curated catalog of San Bernardino County entry-level
classifications grouped by 10 CTE programs. There is no live external API — the
catalog is seeded from import_county_data.py and refreshed when the county
publishes new minimum qualifications.

/api/jobs?pathway_id=<id>
    Returns the county positions tied to the pathway's parent CTE program,
    plus the program metadata. This is the route the dashboard frontend hits
    when a student selects a pathway.

/api/positions/<id>
    Returns one position with full MQ text, pay band, and its career-ladder
    progression chain.
"""

import sqlite3

from flask import Blueprint, jsonify, request, current_app

from database.connection import get_db

jobs_bp = Blueprint("jobs", __name__)


def sanitize_int(value, name="parameter"):
    """Parse value as int; return (int, None) on success or (None, error_response) on failure."""
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, (jsonify({"error": f"Invalid {name}: must be an integer"}), 400)


def _position_row_to_dict(row):
    """Shape a county_positions row for the API. Pay range is omitted when null (NEW classes)."""
    salary = None
    if row["min_hourly"] is not None and row["max_hourly"] is not None:
        salary = f"${row['min_hourly']:.2f} – ${row['max_hourly']:.2f} / hour"
    return {
        "id":          row["id"],
        "job_code":    row["job_code"],
        "title":       row["title"],
        "union_code":  row["union_code"],
        "grade":       row["grade"],
        "min_hourly":  row["min_hourly"],
        "max_hourly":  row["max_hourly"],
        "salary":      salary,
        "mqs_text":    row["mqs_text"],
        "notes":       row["notes"],
        "apply_url":   row["apply_url"],
    }


@jobs_bp.route("/api/jobs", methods=["GET"])
def get_jobs_for_pathway():
    """
    Return the curated county positions tied to a pathway's parent CTE program.
    Required query param: pathway_id (int).
    """
    pathway_id_raw = request.args.get("pathway_id")
    if not pathway_id_raw:
        return jsonify({"error": "pathway_id is required"}), 400
    pathway_id, err = sanitize_int(pathway_id_raw, "pathway_id")
    if err:
        return err

    conn = get_db()
    try:
        pathway = conn.execute(
            """
            SELECT p.id, p.name, p.sector, p.cte_program_id,
                   cp.name AS program_name, cp.description AS program_description
            FROM pathways p
            LEFT JOIN cte_programs cp ON p.cte_program_id = cp.id
            WHERE p.id = ?
            """,
            (pathway_id,),
        ).fetchone()
        if not pathway:
            return jsonify({"error": "Pathway not found"}), 404

        if pathway["cte_program_id"] is None:
            return jsonify({
                "pathway": {
                    "id":     pathway["id"],
                    "name":   pathway["name"],
                    "sector": pathway["sector"],
                },
                "program":  None,
                "positions": [],
                "total":     0,
                "message":   ("This pathway is not currently tied to one of the county's "
                              "10 CTE programs. Speak with your counselor for guidance."),
            })

        positions = conn.execute(
            """
            SELECT id, job_code, title, union_code, grade,
                   min_hourly, max_hourly, mqs_text, notes, apply_url
            FROM county_positions
            WHERE cte_program_id = ?
            ORDER BY (job_code = 'NEW'), title
            """,
            (pathway["cte_program_id"],),
        ).fetchall()

        # Fetch ladder steps for every position in one query, then group in Python.
        position_ids = [p["id"] for p in positions]
        ladder_by_pos = {pid: [] for pid in position_ids}
        postings_by_pos = {pid: [] for pid in position_ids}
        if position_ids:
            placeholders = ",".join("?" * len(position_ids))
            ladder_rows = conn.execute(
                f"""
                SELECT entry_position_id, step_number, title, job_code, notes
                FROM position_ladder_steps
                WHERE entry_position_id IN ({placeholders})
                ORDER BY entry_position_id, step_number
                """,
                position_ids,
            ).fetchall()
            for r in ladder_rows:
                ladder_by_pos[r["entry_position_id"]].append({
                    "step":     r["step_number"],
                    "title":    r["title"],
                    "job_code": r["job_code"],
                    "notes":    r["notes"],
                })
            posting_rows = conn.execute(
                f"""
                SELECT position_id, posting_title, posting_url, posting_close_date, fetched_at
                FROM current_postings
                WHERE position_id IN ({placeholders})
                ORDER BY position_id, posting_title
                """,
                position_ids,
            ).fetchall()
            for r in posting_rows:
                postings_by_pos[r["position_id"]].append({
                    "title":      r["posting_title"],
                    "url":        r["posting_url"],
                    "closes":     r["posting_close_date"],
                    "fetched_at": r["fetched_at"],
                })
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_jobs_for_pathway: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

    positions_out = []
    for p in positions:
        d = _position_row_to_dict(p)
        d["ladder"] = [
            {"step": 1, "title": p["title"], "job_code": p["job_code"], "is_entry": True}
        ] + [
            {**step, "is_entry": False} for step in ladder_by_pos[p["id"]]
        ]
        d["current_postings"] = postings_by_pos[p["id"]]
        d["is_hiring_now"]    = bool(d["current_postings"])
        positions_out.append(d)

    return jsonify({
        "pathway": {
            "id":     pathway["id"],
            "name":   pathway["name"],
            "sector": pathway["sector"],
        },
        "program": {
            "id":          pathway["cte_program_id"],
            "name":        pathway["program_name"],
            "description": pathway["program_description"],
        },
        "positions": positions_out,
        "total":     len(positions_out),
    })


@jobs_bp.route("/api/positions/<int:position_id>", methods=["GET"])
def get_position_detail(position_id):
    """Return one position with its full ladder chain (entry → senior → supervisor)."""
    conn = get_db()
    try:
        position = conn.execute(
            """
            SELECT cp.id, cp.job_code, cp.title, cp.union_code, cp.grade,
                   cp.min_hourly, cp.max_hourly, cp.mqs_text, cp.notes, cp.apply_url,
                   cp.cte_program_id, p.name AS program_name
            FROM county_positions cp
            JOIN cte_programs p ON cp.cte_program_id = p.id
            WHERE cp.id = ?
            """,
            (position_id,),
        ).fetchone()
        if not position:
            return jsonify({"error": "Position not found"}), 404

        ladder = conn.execute(
            """
            SELECT step_number, title, job_code, notes
            FROM position_ladder_steps
            WHERE entry_position_id = ?
            ORDER BY step_number
            """,
            (position_id,),
        ).fetchall()
        postings = conn.execute(
            """
            SELECT posting_title, posting_url, posting_close_date, fetched_at
            FROM current_postings
            WHERE position_id = ?
            ORDER BY posting_title
            """,
            (position_id,),
        ).fetchall()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_position_detail: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

    data = _position_row_to_dict(position)
    data["program"] = {
        "id":   position["cte_program_id"],
        "name": position["program_name"],
    }
    data["current_postings"] = [
        {
            "title":      r["posting_title"],
            "url":        r["posting_url"],
            "closes":     r["posting_close_date"],
            "fetched_at": r["fetched_at"],
        }
        for r in postings
    ]
    data["is_hiring_now"] = bool(data["current_postings"])
    data["ladder"] = [
        {
            "step":     1,
            "title":    position["title"],
            "job_code": position["job_code"],
            "is_entry": True,
        }
    ] + [
        {
            "step":     row["step_number"],
            "title":    row["title"],
            "job_code": row["job_code"],
            "notes":    row["notes"],
            "is_entry": False,
        }
        for row in ladder
    ]
    return jsonify(data)
