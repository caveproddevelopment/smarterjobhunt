import { COMPANY_TYPE_LABELS, DEFAULT_COMPANY_TYPE } from '../lib/companyTypes'

const DEFAULT_FILTERS = {
  title: '',
  postedDays: '',
  companyType: DEFAULT_COMPANY_TYPE,
  remoteOnly: false,
}

const STATUS_LABELS = {
  applied: 'Applied Jobs',
  rejected: 'Rejected Jobs',
  neither: 'Neither Jobs',
  tracked: 'Applied + Rejected Jobs',
}

export default function ActiveFiltersBar({
  filters,
  onChange,
  onJumpToTitleMatch = () => {},
  selectedVariant = null,
  selectedCompany = null,
  selectedStatus = null,
  onReturnToFullList = () => {},
  bookmarked = false,
  onToggleBookmark = () => {},
  bookmarkError = null,
}) {
  // Wrapped in a helper (rather than a single precomputed element) so the
  // "chips" branch below can slot the match-% note in as an extra line
  // underneath the button, while the other two branches (scoped view, no
  // chips) render just the button + any bookmark error as before.
  function renderBookmarkColumn(extra = null) {
    return (
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
        {extra}
      </div>
    )
  }

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
          {renderBookmarkColumn()}
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
      // Clicking the chip's label (not its ×) jumps to the best-matching
      // job in the current list instead of clearing the filter -- exact
      // title match if there is one, otherwise whichever job has the
      // highest match %. The × still just clears, same as every other chip.
      onLabelClick: onJumpToTitleMatch,
      labelTitle: 'Jump to the best-matching job',
    })
  }
  if (filters.postedDays) {
    chips.push({
      key: 'postedDays',
      label: `Last ${filters.postedDays} days`,
      clear: () => onChange({ ...filters, postedDays: '' }),
    })
  }
  // Unlike title/postedDays, this one is a required radio -- there's no
  // "unset" state to fall back to, "both" is just as much an explicit
  // choice as funded or fortune500 (it means "search across both
  // databases", not "no database filter applied"). So it always shows a
  // chip, and its × resets to the sidebar's default rather than to "both".
  if (filters.companyType) {
    chips.push({
      key: 'companyType',
      label: COMPANY_TYPE_LABELS[filters.companyType] || filters.companyType,
      clear: () => onChange({ ...filters, companyType: DEFAULT_COMPANY_TYPE }),
    })
  }
  if (filters.remoteOnly) {
    chips.push({
      key: 'remoteOnly',
      label: 'Remote',
      clear: () => onChange({ ...filters, remoteOnly: false }),
    })
  }

  if (chips.length === 0) {
    return (
      <div className="border-b border-line bg-mist/60 px-6 py-3">
        <div className="flex items-center">{renderBookmarkColumn()}</div>
      </div>
    )
  }

  return (
    <div className="border-b border-line bg-mist/60 px-6 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ink-soft">Active filters:</span>
        {chips.map((chip) =>
          chip.onLabelClick ? (
            <span
              key={chip.key}
              className="flex items-center gap-1.5 rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink"
            >
              <button
                type="button"
                onClick={chip.onLabelClick}
                title={chip.labelTitle}
                className="hover:text-ember"
              >
                {chip.label}
              </button>
              <button
                type="button"
                onClick={chip.clear}
                aria-label={`Clear ${chip.label} filter`}
                className="text-ink-soft hover:text-ink"
              >
                ×
              </button>
            </span>
          ) : (
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
          )
        )}
        {chips.length > 1 && (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="text-xs font-medium text-ember hover:text-flame"
          >
            Clear all
          </button>
        )}
        {renderBookmarkColumn(
          filters.title && (
            <p className="mt-2 whitespace-nowrap text-right text-xs text-ink-soft">
              Match % is based on how closely each job's title and description match your search.
            </p>
          )
        )}
      </div>

    </div>
  )
}