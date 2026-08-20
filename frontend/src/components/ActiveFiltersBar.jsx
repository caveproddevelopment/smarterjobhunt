import { COMPANY_TYPE_LABELS, DEFAULT_COMPANY_TYPE } from '../lib/companyTypes'

const DEFAULT_FILTERS = { title: '', postedDays: '', companyType: DEFAULT_COMPANY_TYPE }

const STATUS_LABELS = {
  applied: 'Applied Jobs',
  rejected: 'Rejected Jobs',
  tracked: 'Applied + Rejected Jobs',
}

export default function ActiveFiltersBar({
  filters,
  onChange,
  selectedVariant = null,
  selectedCompany = null,
  selectedStatus = null,
  onReturnToFullList = () => {},
  bookmarked = false,
  onToggleBookmark = () => {},
  bookmarkError = null,
}) {
  // Wrapped (rather than putting ml-auto on the button itself) so a failed
  // save can show a small message right under the button -- e.g. "You
  // already have this search bookmarked" -- without disturbing the rest of
  // the bar's layout, and without commandeering the whole job-listings
  // panel the way the page-level error banner does.
  const bookmarkButtonEl = (
    <div className="ml-auto flex shrink-0 flex-col items-end gap-1">
      <button
        type="button"
        onClick={onToggleBookmark}
        className="flex items-center gap-1.5 text-xs font-medium text-ink-soft hover:text-ink"
      >
        <span
          aria-hidden="true"
          className={`text-xl leading-none ${bookmarked ? 'text-ember' : 'text-ink-soft'}`}
        >
          {bookmarked ? '★' : '☆'}
        </span>
        Bookmark Search
      </button>
      {bookmarkError && (
        <p className="max-w-[200px] text-right text-xs text-ember">{bookmarkError}</p>
      )}
    </div>
  )

  // Once a variant pill, "See them all", or a "Track Applications" radio is
  // selected, the listing is scoped to just that title, company, or
  // application status. "Return to Full List" and "Current View" move into this same
  // gray bar alongside the bookmark control, instead of living in the white
  // header above. Every scoped view is bookmarkable now (see
  // buildBookmarkName / currentView in JobListings), so the bookmark
  // control always shows here too.
  const scopedLabel = selectedStatus
    ? STATUS_LABELS[selectedStatus]
    : selectedCompany
      ? `All jobs at ${selectedCompany.name}`
      : selectedVariant
  if (scopedLabel) {
    return (
      <div className="border-b border-line bg-mist/60 px-6 py-3">
        <div className="relative flex items-center">
          <button
            type="button"
            onClick={onReturnToFullList}
            className="flex items-center gap-1.5 text-sm font-medium text-ember hover:text-flame"
          >
            <span aria-hidden="true">←</span>
            Return to Full List
          </button>
          <span className="absolute left-1/2 -translate-x-1/2 text-sm font-semibold text-ink">
            Current View: <span className="text-ember">{scopedLabel}</span>
          </span>
          {bookmarkButtonEl}
        </div>
      </div>
    )
  }

  const chips = []

  if (filters.title) {
    chips.push({
      key: 'title',
      label: `Title: "${filters.title}"`,
      clear: () => onChange({ ...filters, title: '' }),
    })
  }
  if (filters.postedDays) {
    chips.push({
      key: 'postedDays',
      label: `Last ${filters.postedDays} days`,
      clear: () => onChange({ ...filters, postedDays: '' }),
    })
  }
  if (filters.companyType && filters.companyType !== DEFAULT_COMPANY_TYPE) {
    chips.push({
      key: 'companyType',
      label: COMPANY_TYPE_LABELS[filters.companyType] || filters.companyType,
      clear: () => onChange({ ...filters, companyType: DEFAULT_COMPANY_TYPE }),
    })
  }

  const bookmarkButton = bookmarkButtonEl

  if (chips.length === 0) {
    return (
      <div className="border-b border-line bg-mist/60 px-6 py-3">
        <div className="flex items-center">{bookmarkButton}</div>
      </div>
    )
  }

  return (
    <div className="border-b border-line bg-mist/60 px-6 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ink-soft">Active filters:</span>
        {chips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            onClick={chip.clear}
            className="flex items-center gap-1.5 rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink hover:bg-line/40"
          >
            {chip.label}
            <span aria-hidden="true" className="text-ink-soft">
              ×
            </span>
          </button>
        ))}
        {chips.length > 1 && (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="text-xs font-medium text-ember hover:text-flame"
          >
            Clear all
          </button>
        )}
        {bookmarkButton}
      </div>

    </div>
  )
}