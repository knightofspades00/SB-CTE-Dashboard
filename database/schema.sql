CREATE TABLE IF NOT EXISTS schools (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    district  TEXT    NOT NULL,
    latitude  REAL,
    longitude REAL,
    UNIQUE(name, district)
);

CREATE TABLE IF NOT EXISTS pathways (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sector      TEXT,
    department  TEXT,
    description TEXT,
    skills      TEXT
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

CREATE TABLE IF NOT EXISTS job_cache (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pathway_id INTEGER NOT NULL REFERENCES pathways(id) ON DELETE CASCADE,
    job_title  TEXT,
    employer   TEXT,
    location   TEXT,
    apply_url  TEXT,
    cached_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_cache_pathway ON job_cache(pathway_id);
