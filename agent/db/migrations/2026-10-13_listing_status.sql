-- 2026-10-13 — companies.listing_status + companies.careers_url
--
-- Run once against the production database BEFORE applying
-- db/fixes/2026-10-13_india_findings.sql. Safe to re-run.
-- The agent works with or without these columns (it checks for them), so
-- deploy order between this file and the new agent code doesn't matter.
--
-- Also copy these statements into backend/db/schema.sql so a fresh
-- database gets them.

-- Why a company is or isn't scraped:
--   active              scrape normally (default)
--   no_online_listings  no careers page, or a careers page with no listings /
--                       email-only / LinkedIn-only. Skipped by default; re-check
--                       periodically with --listing-status active,no_online_listings
--   pdf_notices         jobs are published only as PDF recruitment notices
--                       (PSUs, banks). Skipped until we decide whether JobBeggar
--                       lists notices.
--   needs_review        stored website is parked/hijacked/wrong; a human needs to
--                       find the right URL (then set back to 'active')
--   inactive            company defunct / merged / deliberately dropped
ALTER TABLE companies ADD COLUMN IF NOT EXISTS listing_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_listing_status_check;
ALTER TABLE companies ADD CONSTRAINT companies_listing_status_check
    CHECK (listing_status IN ('active', 'no_online_listings', 'pdf_notices', 'needs_review', 'inactive'));
ALTER TABLE companies ADD COLUMN IF NOT EXISTS listing_status_note TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS listing_status_updated_at TIMESTAMPTZ;

-- Manual careers-page override. When set, the agent tries this URL first
-- (API if it's a supported hiring platform, else a browser scrape) and only
-- falls back to automatic detection if it yields nothing.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS careers_url TEXT;

CREATE INDEX IF NOT EXISTS idx_companies_listing_status ON companies (listing_status);
