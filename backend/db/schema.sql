-- SmarterJobHunt schema
-- Run with: psql -d smarterjobhunt -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS pg_trgm; -- fast ILIKE / fuzzy title search

-- ---------------------------------------------------------------------------
-- companies: one row per employer the scraping agent tracks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    website        TEXT,
    funding_stage  TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (funding_stage IN (
                       'seed', 'series_a', 'series_b', 'series_c_plus',
                       'public', 'bootstrapped', 'unknown'
                   )),
    funding_amount TEXT,               -- raw display string, e.g. "$25,000,000"
    funding_date   DATE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- jobs: one row per posting; this is what the scraping agent will populate
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id             SERIAL PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    department     TEXT,
    location       TEXT,
    date_posted    DATE NOT NULL DEFAULT CURRENT_DATE,
    source_url     TEXT,
    raw_text       TEXT,               -- full scraped description, for matching later
    is_active      BOOLEAN NOT NULL DEFAULT true,
    scraped_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_id   ON jobs (company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_date_posted  ON jobs (date_posted DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_title_trgm   ON jobs USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_jobs_active       ON jobs (is_active) WHERE is_active;

-- Lets the ingestion agent upsert instead of creating duplicate rows on every
-- scrape run. Jobs without a source_url (shouldn't normally happen) fall
-- outside this index and are always inserted fresh.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedup
    ON jobs (company_id, source_url) WHERE source_url IS NOT NULL;

-- ---------------------------------------------------------------------------
-- users: job seekers using the app
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    is_verified    BOOLEAN NOT NULL DEFAULT false,
    resume_text    TEXT,               -- used later to compute match scores
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Safe to re-run: adds the column if this schema.sql is being re-applied
-- against a DB created before email verification existed.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false;

-- ---------------------------------------------------------------------------
-- job_matches: per-user match % against a job (computed by the AI agent later;
-- until then this table can simply be left empty and the API defaults to null)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_matches (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id         INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    match_percent  SMALLINT NOT NULL CHECK (match_percent BETWEEN 0 AND 100),
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, job_id)
);

-- ---------------------------------------------------------------------------
-- user_job_status: the Applied / Rejected toggle + reason from the dashboard
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_job_status (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status           TEXT NOT NULL CHECK (status IN ('applied', 'rejected')),
    reason_rejected  TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, job_id)
);

-- ---------------------------------------------------------------------------
-- saved_searches: the sidebar's "Your saved searches" list
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_searches (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    job_title            TEXT,
    variants            SMALLINT NOT NULL DEFAULT 10,
    posted_within_days  INTEGER,
    funding_filter      TEXT NOT NULL DEFAULT 'both'
                        CHECK (funding_filter IN ('both', 'a', 'b')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_saved_searches_user_id ON saved_searches (user_id);
CREATE INDEX IF NOT EXISTS idx_user_job_status_user_id ON user_job_status (user_id);
CREATE INDEX IF NOT EXISTS idx_job_matches_user_id ON job_matches (user_id);
