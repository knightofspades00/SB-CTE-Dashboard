-- ============================================================================
-- CTE Job Dashboard schema
--
-- Data lives in three logical layers:
--   1. School side  — schools, pathways, school_pathways, careers, pathway_careers
--      (sourced from the city CTE_Connections.xlsx via import_data.py)
--   2. County side  — cte_programs, county_positions, position_ladder_steps
--      (sourced from the county-provided MQs + career-ladder docs via
--      import_county_data.py)
--   3. The bridge    — pathways.cte_program_id maps every fine-grained school
--      pathway up to one of the 10 County CTE Programs so a student selecting
--      a pathway sees the county positions the county has tied to that program.
-- ============================================================================

CREATE TABLE IF NOT EXISTS schools (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    district  TEXT    NOT NULL,
    latitude  REAL,
    longitude REAL,
    UNIQUE(name, district)
);

CREATE TABLE IF NOT EXISTS cte_programs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    description   TEXT,
    display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pathways (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    sector         TEXT,
    department     TEXT,
    description    TEXT,
    skills         TEXT,
    cte_program_id INTEGER REFERENCES cte_programs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS school_pathways (
    school_id  INTEGER NOT NULL REFERENCES schools(id)  ON DELETE CASCADE,
    pathway_id INTEGER NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
    PRIMARY KEY (school_id, pathway_id)
);

CREATE TABLE IF NOT EXISTS careers (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS pathway_careers (
    pathway_id INTEGER NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
    career_id  INTEGER NOT NULL REFERENCES careers(id)  ON DELETE CASCADE,
    PRIMARY KEY (pathway_id, career_id)
);

-- ---------------------------------------------------------------------------
-- County catalog
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS county_positions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    job_code           TEXT,    -- nullable; "NEW" for positions still in development
    title              TEXT NOT NULL,
    cte_program_id     INTEGER NOT NULL REFERENCES cte_programs(id) ON DELETE CASCADE,
    union_code         TEXT,
    grade              TEXT,
    min_hourly         REAL,
    max_hourly         REAL,
    mqs_text           TEXT,    -- full minimum-qualifications text from the county
    notes              TEXT,
    apply_url          TEXT,    -- deep link to governmentjobs.com/careers/sanbernardino search
    UNIQUE(title, cte_program_id)
);

CREATE TABLE IF NOT EXISTS position_ladder_steps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_position_id INTEGER NOT NULL REFERENCES county_positions(id) ON DELETE CASCADE,
    step_number       INTEGER NOT NULL,    -- 1 = entry, 2 = next step, etc.
    title             TEXT    NOT NULL,
    job_code          TEXT,
    notes             TEXT,
    UNIQUE(entry_position_id, step_number)
);

-- ---------------------------------------------------------------------------
-- Live "currently hiring" overlay
--
-- Wiped and rebuilt by services/refresh_postings.py — each row is a posting
-- that was open on governmentjobs.com/careers/sanbernardino at fetch time AND
-- matched a county_positions title. The presence of any rows for a position
-- drives the green "Hiring now" pill in the UI; their posting_url overrides
-- the catalog-level keyword-search apply_url.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS current_postings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id        INTEGER NOT NULL REFERENCES county_positions(id) ON DELETE CASCADE,
    posting_title      TEXT    NOT NULL,
    posting_url        TEXT    NOT NULL,
    posting_close_date TEXT,
    fetched_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pathways_program ON pathways(cte_program_id);
CREATE INDEX IF NOT EXISTS idx_county_positions_program ON county_positions(cte_program_id);
CREATE INDEX IF NOT EXISTS idx_ladder_position ON position_ladder_steps(entry_position_id);
CREATE INDEX IF NOT EXISTS idx_current_postings_position ON current_postings(position_id);
