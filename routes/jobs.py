"""
routes/jobs.py — REST endpoints for live and cached job listings (/api/jobs).
Resolves a pathway_id to a search keyword, fans out to USA Jobs and JSearch,
merges the results, and falls back gracefully when both APIs are unavailable.
"""

import sqlite3

from flask import Blueprint, jsonify, request, current_app

from database.connection import get_db
from services.job_apis import search_usajobs, search_jsearch, merge_results

jobs_bp = Blueprint("jobs", __name__)

def sanitize_int(value, name="parameter"):
    """Parse value as int; return (int, None) on success or (None, error_response) on failure."""
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, (jsonify({"error": f"Invalid {name}: must be an integer"}), 400)

@jobs_bp.route("/api/jobs", methods=["GET"])
def get_jobs():
    """
    Live job search for a pathway.  Queries USA Jobs and JSearch in parallel keyword tiers,
    merges results, and returns a 503 with a student-friendly message if both APIs fail.
    Required query param: pathway_id (int).  Optional: page (int, default 1).
    """
    pathway_id_raw = request.args.get("pathway_id")
    if not pathway_id_raw:
        return jsonify({"error": "pathway_id is required"}), 400
    pathway_id, err = sanitize_int(pathway_id_raw, "pathway_id")
    if err:
        return err
    page_raw = request.args.get("page", 1)
    page, err = sanitize_int(page_raw, "page")
    if err:
        return err
    page = max(1, page)

    conn = get_db()
    try:
        pathway = conn.execute(
            "SELECT id, name, sector FROM pathways WHERE id = ?", (pathway_id,)
        ).fetchone()
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_jobs: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()

    if not pathway:
        return jsonify({"error": "Pathway not found"}), 404

    # --- USA Jobs ---
    usajobs_result = search_usajobs(
        keyword=pathway["name"],
        location=current_app.config["JOB_SEARCH_LOCATION"],
        radius=current_app.config["JOB_SEARCH_RADIUS"],
        results_per_page=current_app.config["JOB_SEARCH_RESULTS_PER_PAGE"],
        page=page,
        user_agent=current_app.config["USAJOBS_USER_AGENT"],
        api_key=current_app.config["USAJOBS_API_KEY"],
        sector=pathway["sector"],
    )

    # --- JSearch ---
    jsearch_result = search_jsearch(
        keyword=pathway["name"],
        location=current_app.config["JOB_SEARCH_LOCATION"],
        api_key=current_app.config["JSEARCH_API_KEY"],
        results_per_page=current_app.config["JOB_SEARCH_RESULTS_PER_PAGE"],
    )

    # --- Merge ---
    merged = merge_results([usajobs_result, jsearch_result])

    # Both APIs failed
    both_failed = bool(usajobs_result.get("error")) and bool(jsearch_result.get("error"))
    if both_failed and not merged:
        return jsonify({
            "pathway":       dict(pathway),
            "jobs":          [],
            "total":         0,
            "api_available": False,
            "message":       "Live job listings are temporarily unavailable. Please speak with your counselor."
        }), 503

    return jsonify({
        "pathway":       dict(pathway),
        "jobs":          merged,
        "total":         len(merged),
        "page":          page,
        "api_available": True,
        "sources": {
            "usajobs": len(usajobs_result.get("jobs", [])),
            "jsearch":  len(jsearch_result.get("jobs", [])),
        }
    })

@jobs_bp.route("/api/jobs/cached", methods=["GET"])
def get_cached_jobs():
    """Return pre-fetched job listings from the job_cache table, bypassing live API calls."""
    pathway_id_raw = request.args.get("pathway_id")
    if not pathway_id_raw:
        return jsonify({"error": "pathway_id is required"}), 400
    pathway_id, err = sanitize_int(pathway_id_raw, "pathway_id")
    if err:
        return err

    conn = get_db()
    try:
        pathway = conn.execute(
            "SELECT id, name FROM pathways WHERE id = ?", (pathway_id,)
        ).fetchone()
        if not pathway:
            return jsonify({"error": "Pathway not found"}), 404
        cached = conn.execute("""
            SELECT job_title, employer, location, apply_url, cached_at
            FROM job_cache WHERE pathway_id = ?
            ORDER BY cached_at DESC
        """, (pathway_id,)).fetchall()
        return jsonify({
            "pathway": dict(pathway),
            "jobs":    [dict(j) for j in cached],
            "total":   len(cached),
            "source":  "cache"
        })
    except sqlite3.Error as e:
        current_app.logger.error(f"DB error in get_cached_jobs: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        conn.close()