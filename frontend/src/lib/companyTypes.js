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
  { value: 'midsize', label: 'Mid-Sized US' },
  { value: 'healthcare', label: 'Healthcare Industry' },
]

export const DEFAULT_COMPANY_TYPE = 'funded'

// The Companies checkbox list in the filter sidebar. No "All" entry --
// leaving every real category unchecked (or checking several) is how you
// broaden the search instead.
export const COMPANY_TYPE_FILTER_OPTIONS = [...COMPANY_TYPES]

export const COMPANY_TYPE_LABELS = Object.fromEntries(
  COMPANY_TYPE_FILTER_OPTIONS.map(({ value, label }) => [value, label])
)