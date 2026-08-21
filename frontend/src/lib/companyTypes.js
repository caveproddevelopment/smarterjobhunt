// Single source of truth for the "Company Database" categories a company
// (and in turn a search/bookmark) can be scoped to. To add a new database
// in the future, add ONE entry to COMPANY_TYPES below -- the filter radios
// (FilterSidebar), the active-filter chip label (ActiveFiltersBar), and the
// bookmark name suffix (JobListings) all derive from this list, so none of
// those files need to change.
//
// Backend note: this can't be shared across the JS/Python boundary, so the
// matching lists on the backend still need their own update when you add a
// database here:
//   - COMPANY_TYPES in backend/routes/jobs.py (the API's allowlist for the
//     ?company_type= query param -- silently ignores unknown values rather
//     than erroring, so it's easy to forget)
//   - the CHECK (company_type IN (...)) constraints on companies.company_type
//     and saved_searches.company_type in backend/db/schema.sql
//   - whatever tags companies with company_type during scraping/ingestion
export const COMPANY_TYPES = [
  { value: 'funded', label: 'Funded Startups' },
  { value: 'fortune500', label: 'Fortune 500' },
  { value: 'indianmajor', label: 'Major Indian Companies' },
]

export const DEFAULT_COMPANY_TYPE = 'funded'

// A search/bookmark's Company Database filter always additionally offers
// "Both" (no restriction) on top of the real categories above -- unlike
// those, "Both" isn't something a company itself can be, so it's added
// here rather than being one of the COMPANY_TYPES entries.
export const COMPANY_TYPE_FILTER_OPTIONS = [...COMPANY_TYPES, { value: 'both', label: 'Both' }]

export const COMPANY_TYPE_LABELS = Object.fromEntries(
  COMPANY_TYPE_FILTER_OPTIONS.map(({ value, label }) => [value, label])
)