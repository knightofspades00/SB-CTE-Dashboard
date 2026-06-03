"""
services/job_apis.py
--------------------
Job API integrations for the CTE Job Dashboard.
Active sources:
  1. USA Jobs  — federal government positions
  2. JSearch   — aggregates Indeed, LinkedIn, ZipRecruiter, Glassdoor (via RapidAPI)

Results from both sources are merged and deduplicated before being returned.
"""

import re
import logging
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared keyword utilities
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "and", "or", "the", "of", "in", "for", "a", "an", "to", "with",
    "by", "at", "from", "into", "through", "during", "including",
    "&", "-", "studies", "study", "advanced",
}

def _clean(text):
    """Strip punctuation and filter out stop words; return a list of meaningful tokens."""
    text = re.sub(r"[,\(\)\.\-/]", " ", text or "")
    return [w for w in text.split() if w.lower() not in _STOP_WORDS and len(w) > 2]

def build_keywords(pathway_name, sector=None):
    """
    Build an ordered list of fallback search keywords from a pathway name and optional sector.
    Returns up to three tiers: full name tokens → first two name tokens → sector tokens (or single word).
    Search functions try tier 1 first and fall back to broader terms only when no results are found.
    """
    name_words   = _clean(pathway_name)
    sector_words = _clean(sector or "")
    tier1 = " ".join(name_words[:3]) if name_words else None
    tier2 = " ".join(name_words[:2]) if len(name_words) >= 2 else tier1
    tier3 = " ".join(sector_words[:2]) if sector_words else (name_words[0] if name_words else None)
    tiers = []
    seen  = set()
    for t in [tier1, tier2, tier3]:
        if t and t not in seen:
            tiers.append(t)
            seen.add(t)
    return tiers


# ---------------------------------------------------------------------------
# USA Jobs
# ---------------------------------------------------------------------------

def _is_valid_location(locations):
    """Return True if at least one position location is in California or marked remote/anywhere."""
    if not locations:
        return True
    for loc in locations:
        state = loc.get("CountrySubDivisionCode", "")
        city  = loc.get("LocationName", "") or ""
        if state == "CA":
            return True
        if "anywhere" in city.lower() or "remote" in city.lower():
            return True
    return False

def _usajobs_single(keyword, location, radius, results_per_page, page, user_agent, api_key):
    """
    Execute one USA Jobs API search and return normalised job dicts.
    Returns {"jobs": [...], "error": None} on success or {"jobs": [], "error": str} on failure.
    Jobs outside California (and not remote) are filtered out by _is_valid_location.
    """
    headers = {
        "User-Agent":        user_agent,
        "Authorization-Key": api_key or "",
    }
    params = {
        "Keyword":        keyword,
        "LocationName":   location,
        "Radius":         str(radius),
        "ResultsPerPage": str(results_per_page),
        "Page":           str(page),
        "WhoMayApply":    "all",
        "SortField":      "OpenDate",
        "SortDirection":  "Desc",
    }
    try:
        response = requests.get(
            "https://data.usajobs.gov/api/search",
            headers=headers, params=params, timeout=10
        )
    except requests.exceptions.Timeout:
        return {"jobs": [], "error": "USA Jobs timed out."}
    except requests.exceptions.ConnectionError:
        return {"jobs": [], "error": "Could not connect to USA Jobs."}
    except Exception as e:
        return {"jobs": [], "error": f"USA Jobs unexpected error: {e}"}

    if response.status_code == 401:
        return {"jobs": [], "error": "USA Jobs authentication failed."}
    if response.status_code == 429:
        return {"jobs": [], "error": "USA Jobs rate limit reached."}
    if response.status_code != 200:
        return {"jobs": [], "error": f"USA Jobs HTTP {response.status_code}"}

    items = response.json().get("SearchResult", {}).get("SearchResultItems", [])
    jobs  = []
    for item in items:
        matched   = item.get("MatchedObjectDescriptor", {})
        locations = matched.get("PositionLocation", [])
        if not _is_valid_location(locations):
            continue
        org      = matched.get("OrganizationName", "")
        dept     = matched.get("DepartmentName", "")
        employer = org or dept or "Federal Agency"
        location_str = ""
        if locations:
            city         = locations[0].get("LocationName", "")
            state        = locations[0].get("CountrySubDivisionCode", "")
            location_str = f"{city}, {state}".strip(", ")
        salary = None
        for pay in matched.get("PositionRemuneration", []):
            min_p, max_p, interval = pay.get("MinimumRange",""), pay.get("MaximumRange",""), pay.get("RateIntervalCode","")
            if min_p and max_p:
                try:
                    salary = f"${float(min_p):,.0f} – ${float(max_p):,.0f} / {interval}"
                except ValueError:
                    pass
                break
        apply_url = (matched.get("ApplyURI") or [""])[0]
        jobs.append({
            "title":     matched.get("PositionTitle", "Unknown Title"),
            "employer":  employer,
            "location":  location_str,
            "salary":    salary,
            "posted":    matched.get("PublicationStartDate"),
            "apply_url": apply_url,
            "source":    "usajobs",
        })
    return {"jobs": jobs, "error": None}

def search_usajobs(keyword, location, radius, results_per_page, page, user_agent, api_key, sector=None):
    """
    Search USA Jobs using progressive keyword tiers built from the pathway name and sector.
    Tries tier 1 (most specific) first; falls back to broader tiers only when zero results are returned.
    Hard-stops immediately on auth or rate-limit errors rather than wasting further requests.
    Returns {"jobs": [...], "total": int, "error": str|None}.
    """
    if not user_agent:
        return {"jobs": [], "total": 0, "error": "USA Jobs User-Agent not configured."}
    for i, kw in enumerate(build_keywords(keyword, sector), 1):
        logger.info(f"USA Jobs tier {i}: '{kw}'")
        result = _usajobs_single(kw, location, radius, results_per_page, page, user_agent, api_key)
        if result["error"] and ("authentication" in result["error"] or "rate limit" in result["error"]):
            return {**result, "total": 0}
        if result["jobs"]:
            return {"jobs": result["jobs"], "total": len(result["jobs"]), "error": None}
    return {"jobs": [], "total": 0, "error": None}


# ---------------------------------------------------------------------------
# JSearch (RapidAPI) — aggregates Indeed, LinkedIn, ZipRecruiter, Glassdoor
# ---------------------------------------------------------------------------

def search_jsearch(keyword, location, api_key, results_per_page=10):
    """
    Searches JSearch via RapidAPI.
    Returns jobs from Indeed, LinkedIn, ZipRecruiter, and Glassdoor combined.
    Free tier: 200 requests/month.
    results_per_page caps the returned list (JSearch always returns one page of ~10
    items per request; we cap client-side so callers actually get what they asked for).
    """
    if not api_key:
        logger.warning("JSEARCH_API_KEY not set — skipping JSearch.")
        return {"jobs": [], "total": 0, "error": "JSearch API key not configured."}

    headers = {
        "X-RapidAPI-Key":  api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query":          f"{keyword} in {location}",
        "page":           "1",
        "num_pages":      "1",
        "date_posted":    "month",
        "employment_types": "FULLTIME,PARTTIME",
    }

    try:
        response = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers=headers, params=params, timeout=20
        )
    except requests.exceptions.Timeout:
        return {"jobs": [], "total": 0, "error": "JSearch timed out."}
    except requests.exceptions.ConnectionError:
        return {"jobs": [], "total": 0, "error": "Could not connect to JSearch."}
    except Exception as e:
        return {"jobs": [], "total": 0, "error": f"JSearch unexpected error: {e}"}

    if response.status_code == 401 or response.status_code == 403:
        return {"jobs": [], "total": 0, "error": "JSearch authentication failed — check your RapidAPI key."}
    if response.status_code == 429:
        return {"jobs": [], "total": 0, "error": "JSearch rate limit reached."}
    if response.status_code != 200:
        return {"jobs": [], "total": 0, "error": f"JSearch HTTP {response.status_code}"}

    data  = response.json()
    items = data.get("data", [])
    jobs  = []

    for item in items:
        salary = None
        try:
            min_sal = float(item.get("job_min_salary") or 0)
            max_sal = float(item.get("job_max_salary") or 0)
        except (ValueError, TypeError):
            min_sal = max_sal = 0
        if min_sal > 0 and max_sal > 0:
            period = item.get("job_salary_period", "year")
            salary = f"${min_sal:,.0f} – ${max_sal:,.0f} / {period}"

        jobs.append({
            "title":     item.get("job_title", "Unknown Title"),
            "employer":  item.get("employer_name", "Unknown Employer"),
            "location":  f"{item.get('job_city', '')}, {item.get('job_state', '')}".strip(", "),
            "salary":    salary,
            "posted":    item.get("job_posted_at_datetime_utc"),
            "apply_url": item.get("job_apply_link", ""),
            "source":    "jsearch",
        })

    jobs = jobs[:results_per_page]
    logger.info(f"JSearch returned {len(jobs)} jobs for '{keyword}'")
    return {"jobs": jobs, "total": len(jobs), "error": None}


# ---------------------------------------------------------------------------
# Merge utility — combines and deduplicates results from all sources
# ---------------------------------------------------------------------------

def merge_results(results_list, max_total=20):
    """
    Takes a list of result dicts from multiple APIs.
    Deduplicates by job title + employer (case-insensitive).
    USA Jobs results come first, then JSearch.
    Caps at max_total.
    """
    seen = set()
    merged = []
    for result in results_list:
        for job in result.get("jobs", []):
            key = (job.get("title", "").lower().strip(), job.get("employer", "").lower().strip())
            if key not in seen:
                seen.add(key)
                merged.append(job)
    return merged[:max_total]