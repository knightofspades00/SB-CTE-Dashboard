# CTE Job Dashboard

A web application that connects high school students in San Bernardino County to real local job listings matched to their Career Technical Education (CTE) pathways. Built for the City of San Bernardino student portal.

---

## Table of Contents

- [For City Staff and Administrators](#for-city-staff-and-administrators)
- [For Engineers](#for-engineers)

---

# For City Staff and Administrators

This section explains how to use and maintain the dashboard without writing any code.

## What this app does

The CTE Job Dashboard gives students two ways to find jobs:

- **"I have a pathway"** — A student picks their school and their CTE program. The app shows real local job listings that match that program.
- **"I'm exploring careers"** — A student picks a career they're interested in. The app recommends which CTE programs lead to that career and shows matching job listings.

Job listings are pulled in real time from two sources: **USA Jobs** (federal government positions) and **JSearch** (aggregates Indeed, LinkedIn, ZipRecruiter, and Glassdoor).

---

## How to update school, pathway, or career data

All data — schools, districts, pathways, careers — comes from the city's Excel spreadsheet. No code editing is needed to update it.

**When the spreadsheet changes:**

1. Replace the file at `database/CTE_Connections.xlsx` with the updated version. Keep the filename exactly the same.
2. Open a terminal in the project folder and run:

```bash
source venv/bin/activate
python database/import_data.py
```

3. The database will update automatically. Refresh the app.

**Spreadsheet format requirements:**

The spreadsheet must have exactly three sheets with these names:

| Sheet name | What it contains |
|---|---|
| `School Filter Step 1` | Column 0: District name. Column 1: School name. Columns 2+: Pathway names — mark with an `X` if the school offers that pathway. |
| `Occupational Sector Skills 2` | Occupation sectors, departments, certifications, program descriptions, skills |
| `Occupational Sector Connect  3` | CTE program names and the career pathways they lead to (semicolon-separated) |

> **Important:** Sheet 3's name has two spaces before the `3`. This must be preserved exactly.

---

## What to do if the app shows no job listings

If students see "Live job listings are temporarily unavailable":

1. The USA Jobs or JSearch API may be temporarily down. This is normal — both services have occasional outages.
2. The app will recover automatically when the service comes back.
3. If the issue persists for more than a day, contact your engineering team to check the API keys.

---

## What to do if school map markers are missing

School locations are stored as coordinates in the database. If a new school is added and doesn't appear on the map:

1. Add it to the spreadsheet and run the import script (see above).
2. Then run the geocoding script to automatically look up its coordinates:

```bash
python database/geocode_schools.py
```

If a school still doesn't appear, its address may need to be set manually. Contact your engineering team.

---

## Daily job cache

A background script (`services/cache_pipeline.py`) pre-fetches job listings for every pathway once per day and saves them to the database. This means the app always has job data ready even before a student searches. This script runs separately from the main app in its own terminal window.

---

# For Engineers

This section covers setup, configuration, architecture, and deployment.

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Operating system | Linux, macOS, or Windows |
| Database | SQLite (no server needed — file-based) |

---

## First-time setup

```bash
# 1. Clone or copy the project folder
cd cte_dashboard

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Open .env and fill in all API keys (see Environment Variables below)

# 5. Copy the city spreadsheet into the database folder
# Rename it to: database/CTE_Connections.xlsx

# 6. Initialise the database
python database/init_db.py

# 7. Import spreadsheet data
python database/import_data.py

# 8. Geocode school locations (one-time, uses Nominatim — no key required)
python database/geocode_schools.py

# 9. Run the app
python app.py
```

The app will be available at `http://localhost:5000`.

---

## Environment variables

All secrets and configuration live in `.env`. Never commit this file.

```env
# Flask
FLASK_SECRET_KEY=replace-with-a-long-random-string
FLASK_ENV=development

# USA Jobs API
# Register at: https://developer.usajobs.gov/APIRequest/Index
USAJOBS_USER_AGENT=your-email@cityofsanbernardino.gov
USAJOBS_API_KEY=your-usajobs-api-key-here

# JSearch API (via RapidAPI)
# Register at: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
# Free tier: 200 requests/month
JSEARCH_API_KEY=your-rapidapi-key-here

# Google Maps (used only if switching back from Leaflet)
GOOGLE_MAPS_API_KEY=your-google-maps-api-key-here

# Job search configuration
JOB_SEARCH_LOCATION=San Bernardino, CA
JOB_SEARCH_RADIUS=20
JOB_SEARCH_RESULTS_PER_PAGE=10

# Database
DATABASE_PATH=database/cte_dashboard.db

# Cache pipeline
CACHE_REFRESH_HOURS=24
```

---

## Project structure

```
cte_dashboard/
├── app.py                        ← Flask entry point, registers all blueprints
├── .env                          ← Real secrets — never commit
├── .env.example                  ← Safe template to share/commit
├── .gitignore
├── requirements.txt
│
├── config/
│   ├── __init__.py
│   └── settings.py               ← Single source of truth for all config
│
├── database/
│   ├── schema.sql                ← Table definitions — edit to change DB structure
│   ├── init_db.py                ← Creates empty database from schema.sql
│   ├── import_data.py            ← Reads spreadsheet → populates all tables
│   ├── geocode_schools.py        ← One-time: looks up lat/lng for all schools
│   ├── CTE_Connections.xlsx      ← City spreadsheet — not in version control
│   └── cte_dashboard.db          ← SQLite database — not in version control
│
├── routes/
│   ├── __init__.py
│   ├── schools.py                ← /api/schools, /api/schools/<id>/pathways
│   ├── pathways.py               ← /api/pathways, /api/pathways/<id>, /api/pathways/by-career/<id>
│   ├── careers.py                ← /api/careers
│   └── jobs.py                   ← /api/jobs, /api/jobs/cached
│
├── services/
│   ├── __init__.py
│   ├── job_apis.py               ← USA Jobs + JSearch integrations + merge logic
│   └── cache_pipeline.py         ← Daily background job pre-fetch
│
├── templates/
│   └── index.html                ← Single-page app shell
│
└── static/
    ├── css/
    │   └── styles.css
    └── js/
        └── app.js                ← All frontend logic (map, dropdowns, job cards)
```

---

## API routes

| Method | Route | Description |
|---|---|---|
| GET | `/` | Serves the single-page app |
| GET | `/health` | Health check — returns `{"status": "ok"}` |
| GET | `/api/schools` | All schools with district, coordinates, pathway count |
| GET | `/api/schools/<id>/pathways` | Pathways offered at a specific school |
| GET | `/api/pathways` | All pathways grouped by sector |
| GET | `/api/pathways/<id>` | Full pathway detail including schools and careers |
| GET | `/api/pathways/by-career/<id>` | Pathways that lead to a given career (Flow 2) |
| GET | `/api/careers` | All career titles |
| GET | `/api/jobs?pathway_id=<id>` | Live job search — merges USA Jobs + JSearch |
| GET | `/api/jobs/cached?pathway_id=<id>` | Pre-cached jobs from daily pipeline |

Full request/response documentation is in `API_REFERENCE.md`.

---

## Database schema

| Table | Rows (approx.) | Description |
|---|---|---|
| `schools` | 78 | High schools with district and lat/lng |
| `pathways` | 82 | CTE programs with sector, description, skills |
| `school_pathways` | 406 | Many-to-many: which schools offer which pathways |
| `careers` | 106 | Individual career titles |
| `pathway_careers` | 133 | Many-to-many: which careers each pathway leads to |
| `job_cache` | varies | Pre-cached jobs populated by cache_pipeline.py |

To reset and re-import:

```bash
rm database/cte_dashboard.db
python database/init_db.py
python database/import_data.py
python database/geocode_schools.py
```

---

## Job API architecture

The app queries two APIs on every live job search and merges the results:

1. **USA Jobs** — federal government positions only. Free, no rate limit concerns. Searches within the configured radius of San Bernardino. Uses a 3-tier keyword fallback (specific → broader → sector) to ensure results for every pathway.

2. **JSearch (RapidAPI)** — aggregates Indeed, LinkedIn, ZipRecruiter, and Glassdoor. Free tier: 200 requests/month. Returns local private employer listings that USA Jobs cannot cover.

Results are merged and deduplicated by job title + employer before being returned. USA Jobs results appear first.

**To add more job sources in the future:** Add a new `search_*` function to `services/job_apis.py` and include its result in the `merge_results()` call in `routes/jobs.py`. Placeholder functions for Adzuna, Indeed, and LinkedIn are already stubbed out in `job_apis.py`.

---

## Running the cache pipeline

The cache pipeline pre-fetches jobs for all 82 pathways daily. Run it in a separate terminal:

```bash
source venv/bin/activate
python services/cache_pipeline.py
```

It runs immediately on start, then repeats every `CACHE_REFRESH_HOURS` hours. On the city's production server this should be set up as a systemd service or cron job.

---

## Production deployment (Linux server)

```bash
# Install production server
pip install gunicorn

# Run with gunicorn (4 workers)
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```

**Windows servers:** Replace gunicorn with waitress:

```bash
pip install waitress
waitress-serve --port=8000 "app:create_app()"
```

Set `FLASK_ENV=production` in `.env` before deploying.

---

## Authentication

Authentication is **not built into this app.** It is handled externally by the city's portal SSO. Every location in the codebase where user identity would be consumed is marked with a `<!-- USER AUTH PLACEHOLDER -->` comment in `templates/index.html`.

---

## Map

The app uses **Leaflet.js with OpenStreetMap tiles** — completely free, no API key required. School markers are rendered from the `/api/schools` JSON response. Coordinates are stored in the `schools` table and populated by `database/geocode_schools.py`.

---

## Known limitations

| Issue | Cause | Planned fix |
|---|---|---|
| JSearch free tier caps at 200 requests/month | RapidAPI free plan limit | Upgrade to paid plan or add Adzuna as a second private-sector source |
| USA Jobs only covers federal positions | By design — USA Jobs is federal only | JSearch covers private employers |
| Some pathways return zero listings | No matching jobs in the area at search time | Expected behavior — counselor referral message is shown |

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `python-dotenv` | Loads `.env` into environment |
| `requests` | HTTP calls to job APIs |
| `openpyxl` | Reads city Excel spreadsheets |
| `schedule` | Cross-platform background job scheduler |
| `gunicorn` | Production WSGI server (Linux/macOS) |