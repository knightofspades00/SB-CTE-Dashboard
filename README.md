# CTE Career Dashboard

A web application that connects high school students in San Bernardino County to **County of San Bernardino entry-level job classifications** tied to their Career Technical Education (CTE) pathway. Students see the actual county positions they could apply for, the minimum qualifications, the pay range, and the career-ladder progression from entry through supervisor — plus a direct link to current postings on the county jobs portal.

---

## Table of Contents

- [For City Staff and Administrators](#for-city-staff-and-administrators)
- [For Engineers](#for-engineers)

---

# For City Staff and Administrators

This section explains how to use and maintain the dashboard without writing any code.

## What this app does

The dashboard gives students two ways to explore county careers:

- **"I have a pathway"** — A student picks their school and CTE pathway. The app shows the county's entry-level positions tied to that pathway's program, with minimum qualifications, pay range, and the full progression ladder up to supervisor.
- **"I'm exploring careers"** — A student picks a career they're interested in. The app recommends which CTE pathways lead to that career and shows the same county positions.

Position data is **provided by the County of San Bernardino** — a curated catalog of entry-level classifications organised into ten CTE program groups (Automotive, Arts/Media, Business, Patient Care, Building & Construction, Education/Child Dev/Family Services, Energy/Environment/Utilities, Hospitality, ICT, Public Service). Each position links to the live county jobs portal at [governmentjobs.com/careers/sanbernardino](https://www.governmentjobs.com/careers/sanbernardino) so students can see whether the role is currently posting and apply.

---

## How to update school, pathway, or career data

School and pathway data come from the city's Excel spreadsheet. When it changes:

1. Replace the file at `database/CTE_Connections.xlsx` with the updated version. Keep the filename exactly the same.
2. Open a terminal in the project folder and run:

```bash
python database/import_data.py
python database/import_county_data.py    # re-runs the pathway → county program mapping
```

The database will update automatically. Refresh the app.

**Spreadsheet format requirements:** the file must have exactly three sheets named `School Filter Step 1`, `Occupational Sector Skills 2`, and `Occupational Sector Connect  3` (Sheet 3 has two spaces before the `3`).

---

## How to update county positions or minimum qualifications

The county catalog (42 entry-level positions and their career ladders) is encoded in `database/import_county_data.py`. When the county publishes new MQs or adds/removes a classification:

1. Open `database/import_county_data.py` in any editor.
2. Edit the `POSITIONS` list for MQ changes, the `LADDERS` dict for progression changes, and the `PROGRAMS` list if a new program is added.
3. Run:

```bash
python database/import_county_data.py
```

The script is idempotent — re-running upserts changes and rebuilds the ladders.

---

## What to do if a pathway shows no positions

If a student picks a pathway and the catalog says "No county positions tied to this pathway yet," that pathway's sector isn't currently mapped to one of the county's ten CTE programs (common for Agriculture, Engineering, Manufacturing). That is expected behaviour — the counselor message is shown. To extend coverage, edit the `SECTOR_TO_PROGRAM` mapping in `database/import_county_data.py` and re-run.

---

## What to do if school map markers are missing

School locations are stored as coordinates in the database. If a new school is added and doesn't appear on the map:

1. Add it to the spreadsheet and run `python database/import_data.py`.
2. Then run the geocoding script:

```bash
python database/geocode_schools.py
```

If a school still doesn't appear, its address may need to be set manually. Contact your engineering team.

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
# 1. Clone the repo
git clone https://github.com/<your-fork>/SB-CTE-Dashboard.git
cd SB-CTE-Dashboard

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env              # or: copy .env.example .env (Windows)

# 5. One-shot bootstrap — initialises DB, imports schools/pathways/careers
#    from the bundled xlsx, applies SBCUSD coordinates, seeds the county
#    catalog (programs, positions, MQs, ladders), and reads the most recent
#    currently_hiring.json if present.
python database/bootstrap.py

# 6. Run the app
python app.py
```

The app will be available at `http://localhost:5000`.

Individual steps (still available for advanced workflows):

```bash
python database/init_db.py            # schema only
python database/import_data.py        # school + pathway data from xlsx
python database/geocode_schools.py    # coords (Nominatim + SBCUSD overrides)
python database/import_county_data.py # county catalog seed
```

---

## Environment variables

The dashboard reads no external API keys — the catalog is local. The only required configuration is the Flask secret and (optionally) the database path.

```env
FLASK_SECRET_KEY=replace-with-a-long-random-string
FLASK_ENV=development
DATABASE_PATH=database/cte_dashboard.db
```

Never commit your real `.env`.

---

## Project structure

```
SB-CTE-Dashboard/
├── app.py                          ← Flask entry point, registers all blueprints
├── .env                            ← Real secrets — never commit
├── .env.example
├── .gitignore
├── requirements.txt
│
├── config/
│   └── settings.py                 ← FLASK_* + DATABASE_PATH
│
├── Dockerfile                      ← Production container (gunicorn + bundled DB seed)
├── .dockerignore
├── render.yaml                     ← Render Blueprint (one-click deploy)
│
├── database/
│   ├── schema.sql                  ← Table definitions
│   ├── connection.py               ← Shared get_db() helper
│   ├── init_db.py                  ← Creates / migrates schema
│   ├── bootstrap.py                ← One-shot first-deploy initialiser (idempotent)
│   ├── import_data.py              ← Loads schools/pathways/careers from CTE_Connections.xlsx
│   ├── import_county_data.py       ← Loads 10 programs, 42 positions, MQs, ladders
│   ├── geocode_schools.py          ← Lat/lng for every school (Nominatim + SBCUSD overrides)
│   ├── CTE_Connections.xlsx        ← School/pathway data — committed (private repo)
│   ├── currently_hiring.json       ← Daily refresh output, committed by GitHub Actions
│   └── cte_dashboard.db            ← SQLite database — not in version control
│
├── routes/
│   ├── schools.py                  ← /api/schools, /api/schools/<id>/pathways
│   ├── pathways.py                 ← /api/pathways, /api/pathways/<id>, /api/pathways/by-career/<id>
│   ├── careers.py                  ← /api/careers
│   ├── programs.py                 ← /api/programs, /api/programs/<id>
│   └── jobs.py                     ← /api/jobs?pathway_id=<id>, /api/positions/<id>
│
├── .github/workflows/
│   ├── refresh-hiring.yml          ← Daily Playwright scrape, commits currently_hiring.json
│   └── pages.yml                   ← Build static site + deploy to GitHub Pages
│
├── scripts/
│   ├── build_static.py             ← Pre-bake /api/* responses into docs/data/*.json for Pages
│
│   ├── register-refresh-task.ps1   ← Self-installing Windows Task Scheduler entry for the daily refresh
│   └── refresh-postings.sh         ← Linux/macOS cron wrapper for the daily refresh
│
├── services/
│   └── refresh_postings.py         ← Daily NeoGov scrape → current_postings (Playwright + JSON fallback)
│
├── templates/
│   └── index.html                  ← Single-page app shell
│
└── static/
    ├── css/styles.css
    └── js/app.js                   ← All frontend logic
```

---

## API routes

| Method | Route | Description |
|---|---|---|
| GET | `/` | Serves the single-page app |
| GET | `/health` | Health check — `{"status": "ok"}` |
| GET | `/api/schools` | All schools with district, coordinates, pathway count |
| GET | `/api/schools/<id>/pathways` | Pathways offered at a specific school |
| GET | `/api/pathways` | All pathways grouped by sector |
| GET | `/api/pathways/<id>` | Full pathway detail including schools and careers |
| GET | `/api/pathways/by-career/<id>` | Pathways that lead to a given career (Flow 2) |
| GET | `/api/careers` | All career titles |
| GET | `/api/programs` | The 10 county CTE programs with position counts |
| GET | `/api/programs/<id>` | One program with its positions and the school pathways tied to it |
| GET | `/api/jobs?pathway_id=<id>` | County positions for a pathway's CTE program, with ladder steps |
| GET | `/api/positions/<id>` | A single position with full MQ + ladder |
| GET | `/api/refresh-status` | Freshness + per-program counts for the live "Hiring now" overlay |
| GET | `/programs` | Server-rendered browse page of all 10 county CTE programs (anchor-linkable, print-friendly) |

---

## Database schema

| Table | Rows | Description |
|---|---|---|
| `schools` | 78 | High schools with district and lat/lng |
| `pathways` | 82 | School-side CTE pathways with sector, description, skills, **cte_program_id** |
| `school_pathways` | 406 | Many-to-many: which schools offer which pathways |
| `careers` | 106 | Individual career titles |
| `pathway_careers` | 133 | Many-to-many: which careers each pathway leads to |
| `cte_programs` | 10 | The county's CTE program groupings (Automotive, ICT, Patient Care, …) |
| `county_positions` | 42 | County entry-level classifications with MQ, pay band, governmentjobs link |
| `position_ladder_steps` | ~120 | Career-ladder progression steps beyond each entry position |
| `current_postings` | varies | Live "Hiring now" overlay — refreshed by services/refresh_postings.py |

To reset and re-import everything:

```bash
rm database/cte_dashboard.db
python database/init_db.py
python database/import_data.py
python database/geocode_schools.py
python database/import_county_data.py
```

---

## County catalog architecture

The dashboard does **not** query an external API. All position data is a curated catalog seeded from `database/import_county_data.py`, sourced from two documents the county provided:

1. **Entry Level MQs spreadsheet** (8/13/25) — job codes, titles, union codes, grades, pay ranges, and full minimum-qualifications text for every entry-level classification.
2. **CTE Pathways PDF** — career-progression diagrams showing how each entry job ladders up to mid-level, senior, lead, and supervisor classifications.

The flow when a student picks a pathway:

1. The frontend hits `/api/jobs?pathway_id=<id>`.
2. The route looks up the pathway's `cte_program_id` (back-filled from the pathway's sector by `import_county_data.py`).
3. It returns the program metadata, the positions tied to that program (with MQ text, pay band, and the ladder chain), and the deep link to current postings on governmentjobs.com.
4. Apply buttons open `https://www.governmentjobs.com/careers/sanbernardino?keywords=<title>` so students see whether the classification is currently hiring.

When the county publishes a new MQ revision or adds a classification, edit `POSITIONS`/`LADDERS` in `database/import_county_data.py` and re-run it. Idempotent — existing rows upsert in place.

---

## Production deployment

Four flavours, pick the one that fits.

### A — GitHub Pages (recommended for SBCUSD demo)

The repo includes `scripts/build_static.py`, which pre-bakes every `/api/*` response into a JSON file under `docs/`. The bundled `.github/workflows/pages.yml` workflow runs that builder on a daily cron (right after the hiring refresh) and publishes `docs/` to Pages via the official `actions/deploy-pages` flow.

To enable:

1. In repo **Settings → Pages**, set **Source** to *"GitHub Actions"*. (Nothing else to configure.)
2. Push to `main`. The workflow runs `database/bootstrap.py` → `services/refresh_postings.py` (live Playwright scrape) → `scripts/build_static.py` → uploads `docs/` → deploys to `<user>.github.io/<repo>/`.

Trade-offs:

- ✅ **Free**, no account aside from GitHub, never sleeps, CDN-cached globally
- ✅ Auto-deploys every push + daily refresh = "Hiring now" overlay stays current
- ✅ Works with custom domains via Pages settings
- ⚠️ Data is "fresh as of the last build" (rebuilds daily). No real-time API surface.
- ⚠️ No future room for per-user features (saved favorites, counselor notes). For that, use Render below.

The frontend (`static/js/app.js`) is dual-mode: when the build script injects `window.P2P_STATIC_BASE = "."` into the rendered HTML, `apiFetch()` rewrites `/api/*` → `data/*.json`. Otherwise it hits the live Flask backend. Same JS, both targets.

### B — Render (path to a real Flask URL)

The repo includes a `render.yaml` Blueprint. One-time setup:

1. Sign in at [render.com](https://render.com) and click **New +** → **Blueprint**.
2. Point it at your fork of this repo.
3. Render reads `render.yaml`, provisions the web service, attaches a 1 GB persistent disk for the SQLite file, and auto-generates the `FLASK_SECRET_KEY`. No manual config required.
4. Build step runs `python database/bootstrap.py` which initialises the DB, imports schools/pathways, applies SBCUSD coordinate overrides, seeds the county catalog, and reads the most recent `currently_hiring.json` if present.
5. First deploy takes ~3 minutes. After that the dashboard is live on `<your-slug>.onrender.com`.

The included **GitHub Actions workflow** (`.github/workflows/refresh-hiring.yml`) runs the heavy Playwright scrape in CI on a daily cron, writes `database/currently_hiring.json`, and commits it. Render auto-redeploys on push, so the "Hiring now" overlay stays current without paying for Render's cron tier. Free end-to-end.

### C — Any container host (Fly.io, Azure Web Apps, Cloud Run, self-hosted)

```bash
docker build -t pathways-to-positions .
docker run -p 8000:8000 \
  -e FLASK_SECRET_KEY="$(openssl rand -hex 32)" \
  -v "$PWD/database:/app/database" \
  pathways-to-positions
```

The image bootstraps the SQLite DB at build time so the first request is instant. Mount `database/` to persist `currently_hiring.json` between rebuilds.

### D — Bare metal / VM

```bash
# Linux / macOS
pip install gunicorn
python database/bootstrap.py
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"

# Windows
pip install waitress
python database/bootstrap.py
waitress-serve --port=8000 "app:create_app()"
```

Set `FLASK_ENV=production` (or just omit it — production is the default) and `FLASK_SECRET_KEY` to something random and long.

---

## Authentication

Authentication is **not built into this app.** It is handled externally by the city's portal SSO. Locations in the codebase where user identity would be consumed are marked with a `<!-- USER AUTH PLACEHOLDER -->` comment in `templates/index.html`.

---

## Map

The app uses **Leaflet.js with OpenStreetMap tiles** — completely free, no API key required. School markers are rendered from `/api/schools`. Coordinates are stored on the `schools` table and populated by `database/geocode_schools.py`.

---

## Logos / branding

Three partner marks ship with the project as placeholder SVGs at:

```
static/images/logo-sbcusd.svg     SBCUSD (San Bernardino City Unified)
static/images/logo-county.svg     County of San Bernardino
static/images/logo-avatech.svg    AniVation-Tech Academy (Arroyo Valley HS)
```

To swap in the real artwork, **overwrite the file** in place — same name, same dimensions (any square aspect, SVG/PNG/WebP all work) — and the brand bar, footer pill, and mobile menu pick it up automatically. No code change required.

The placeholders are square-aspect badges sized for 22–40 px on screen. If you replace them with rectangular logos, adjust the relevant CSS:

- `.p2p-brand-logo` (header) — 34 × 34, circular
- `.p2p-footer-logo` (footer) — 22 × 22, circular, AniVation-Tech gets a 24 × 24 maroon ring
- `.p2p-mobile-logo` (mobile top bar) — 28 × 28, circular
- `.p2p-mobile-logos img` (mobile menu) — 32 × 32, circular

---

## Live "Hiring now" overlay

The catalog by itself shows the 42 entry-level classifications regardless of whether they are currently posting. To highlight roles that are actively recruiting on `governmentjobs.com/careers/sanbernardino` right now, the dashboard also maintains a small `current_postings` table that is refreshed daily by `services/refresh_postings.py`.

Two ways to populate it:

### Option A — Live scrape (recommended)

NeoGov's portal renders job listings entirely via client-side JavaScript, so we need a headless browser. Playwright handles it:

```bash
# One-time install of Playwright + Chromium (~150 MB)
pip install playwright
playwright install chromium

# Manual refresh any time:
python services/refresh_postings.py

# Dry-run (show matches but do not touch the DB):
python services/refresh_postings.py --print
```

Verified output against the real portal: walks all paginated postings (~222 at any given time), matches them to the 42 catalog classifications by strict title prefix, and intentionally skips higher-rung postings (Senior X, Lead X, Supervising X) so the Hiring-now pill only fires for entry-level openings students can realistically apply to.

#### Schedule it to run daily

**Windows Task Scheduler** — a self-installing PowerShell script ships in `scripts/`:

```powershell
# Register (default daily at 06:00 local time):
pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1

# Custom time:
pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1 -Time 07:30

# Remove:
pwsh -ExecutionPolicy Bypass -File scripts\register-refresh-task.ps1 -Remove
```

Logs are written to `scripts/refresh.log`. Inspect with:

```powershell
Get-ScheduledTaskInfo -TaskName "Pathways-to-Positions-Refresh"
Get-Content scripts\refresh.log -Tail 20
```

**Linux / macOS cron** — use the included wrapper script. `crontab -e` and add:

```cron
0 6 * * * /path/to/SB-CTE-Dashboard/scripts/refresh-postings.sh
```

The wrapper activates the venv if present, runs the refresh, and appends to `scripts/refresh.log`.

### Option B — Hand-edited JSON

If Playwright is not an option (or you want to seed test data), create `database/currently_hiring.json` with the open postings you want to surface. The refresh script reads it as a fallback when Playwright is unavailable.

```json
[
  {
    "title":  "Office Assistant",
    "url":    "https://www.governmentjobs.com/jobs/12345-1/office-assistant",
    "closes": "2026-06-30"
  },
  {
    "title":  "GIS Technician Trainee",
    "url":    "https://www.governmentjobs.com/jobs/12346-1/gis-technician-trainee"
  }
]
```

Then run `python services/refresh_postings.py --json`. The file is gitignored — it's session data, not source code.

### What the overlay drives

When at least one row exists in `current_postings` for a position:

- A green **● Hiring now** pill appears on the position card
- The Apply button text changes from "See current postings" to "Apply now" and points at the live posting URL instead of the keyword search
- If multiple postings match (e.g. several Office Assistant openings in different departments), the card lists each one with its closing date

When `current_postings` is empty (initial state, or after a refresh found nothing matching), the dashboard falls back to keyword-search Apply links — the same behaviour shipped before the overlay was added.

---

## Known limitations

| Issue | Cause | Fix |
|---|---|---|
| Pathways in Agriculture, Engineering, Manufacturing, or Fashion show no positions | The county's 10 CTE programs don't include those sectors | Out of scope; counselor referral message is shown |
| "NEW" classifications (Graphics Assistant, Media Assistant, Appraiser Assistant) have no MQ or pay band | The county is still developing them | Edit `POSITIONS` in `database/import_county_data.py` when the county publishes details |
| Apply button shows search results, not the specific posting | governmentjobs.com doesn't expose a stable per-classification URL | Acceptable trade-off; students still land on the right job family |

---

## Dependencies

| Package | Purpose |
|---|---|
| `flask` | Web framework |
| `python-dotenv` | Loads `.env` into environment |
| `requests` | HTTP calls for school geocoding (Nominatim) |
| `openpyxl` | Reads city Excel spreadsheets |
| `gunicorn` | Production WSGI server (Linux/macOS) |
