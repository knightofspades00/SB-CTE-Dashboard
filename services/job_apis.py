"""
services/job_apis.py
--------------------
USA Jobs integration for the CTE Job Dashboard.

Scope: federal government positions located within San Bernardino County, CA.

The API search is constrained by:
  1. LocationName + Radius on the request side (geographic bounding circle).
  2. _is_sb_county() post-filter that whitelists known SB County cities and
     installations, dropping any neighbouring-county or out-of-county results
     that fall inside the radius.

JSearch and other private-sector aggregators have been removed by design — this
dashboard is for SBC government job opportunities only.
"""

import re
import logging
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword utilities
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
# San Bernardino County geographic filter
# ---------------------------------------------------------------------------

# Lowercased city / community / installation names that count as "inside SB County."
# Add new entries here when USAJobs surfaces a valid SB County location that the
# filter drops by mistake. Names match the city portion of USAJobs' LocationName,
# i.e. "Barstow, California" → "barstow".
SB_COUNTY_LOCATIONS = {
    # Incorporated cities and towns
    "adelanto", "apple valley", "barstow", "big bear lake", "chino",
    "chino hills", "colton", "fontana", "grand terrace", "hesperia",
    "highland", "loma linda", "montclair", "needles", "ontario",
    "rancho cucamonga", "redlands", "rialto", "san bernardino",
    "twentynine palms", "upland", "victorville", "yucaipa", "yucca valley",
    # Unincorporated communities frequently named in postings
    "big bear city", "bloomington", "crestline", "daggett", "devore",
    "helendale", "joshua tree", "lake arrowhead", "lucerne valley",
    "lytle creek", "mentone", "morongo valley", "mount baldy",
    "muscoy", "newberry springs", "oak hills", "phelan", "pinon hills",
    "running springs", "trona", "wonder valley", "wrightwood",
    # Federal installations within SB County
    "fort irwin", "marine corps air ground combat center",
    "marine corps logistics base", "ntc fort irwin",
}

def _is_sb_county(locations):
    """Return True if at least one listed location is within San Bernardino County.

    Stricter than the previous "any CA job" check: requires both California state
    AND a city/community on the SB_COUNTY_LOCATIONS whitelist. Remote and
    out-of-county jobs are excluded so the dashboard stays geographically focused.
    """
    if not locations:
        return False
    for loc in locations:
        state = (loc.get("CountrySubDivisionCode") or "").strip()
        # USAJobs returns either the state code ("CA") or full name ("California").
        if state not in ("CA", "California"):
            continue
        name = (loc.get("LocationName") or "").strip().lower()
        if not name:
            continue
        # LocationName is typically "City, State" — keep the city portion only.
        city = name.split(",", 1)[0].strip()
        if city in SB_COUNTY_LOCATIONS:
            return True
    return False


# ---------------------------------------------------------------------------
# USA Jobs
# ---------------------------------------------------------------------------

def _usajobs_single(keyword, location, radius, results_per_page, page, user_agent, api_key):
    """
    Execute one USA Jobs API search and return normalised job dicts.
    Returns {"jobs": [...], "error": None} on success or {"jobs": [], "error": str} on failure.
    Jobs outside San Bernardino County are filtered out by _is_sb_county.
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
        if not _is_sb_county(locations):
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
# Result post-processing
# ---------------------------------------------------------------------------

def dedupe_jobs(jobs, max_total=20):
    """Deduplicate jobs by (title, employer) case-insensitively and cap at max_total."""
    seen = set()
    out  = []
    for job in jobs:
        key = (job.get("title", "").lower().strip(), job.get("employer", "").lower().strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
        if len(out) >= max_total:
            break
    return out
