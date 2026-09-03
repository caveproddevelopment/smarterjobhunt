import { COMPANY_TYPE_LABELS, DEFAULT_COMPANY_TYPE } from '../lib/companyTypes'

const DEFAULT_FILTERS = {
  title: '',
  postedDays: '',
  companyTypes: [],
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
  titleVariants = [],
  titleVariantsLoading = false,
  showVariants = false,
  onToggleVariants = () => {},
  variantCounts = {},
  variantCountsLoading = false,
  onSelectVariant = () => {},
}) {
  // Once a variant pill, "See them all", or a "Track Applications" radio is
  // selected, the listing is scoped to just that title, company, or
  // application status. "Return to Full List" and "Current View" show in
  // this same gray bar instead of the chips below.
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
  // Display chips for selected company types - multiple types can be selected
  if (filters.companyTypes && filters.companyTypes.length > 0) {
    const companyTypeLabels = filters.companyTypes.map((type) => COMPANY_TYPE_LABELS[type])
    chips.push({
      key: 'companyTypes',
      label: companyTypeLabels.join(', '),
      clear: () => onChange({ ...filters, companyTypes: [DEFAULT_COMPANY_TYPE] }),
    })
  }
  if (filters.remoteOnly) {
    chips.push({
      key: 'remoteOnly',
      label: 'Remote',
      clear: () => onChange({ ...filters, remoteOnly: false }),
    })
  }

  if (chips.length === 0) return null

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
      </div>
      {filters.title && !titleVariantsLoading && titleVariants.length > 0 && (
        <div className="mt-2 text-center">
          <button
            type="button"
            onClick={onToggleVariants}
            className="text-xs font-semibold text-ember hover:text-flame"
          >
            {showVariants ? 'Hide Variants' : 'See Variants'}
          </button>
        </div>
      )}

      {showVariants && (
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          {variantCountsLoading
            ? <span className="text-xs text-ink-soft">Loading variant match counts…</span>
            : titleVariants.map((variant) => {
                const count = variantCounts[variant] ?? 0
                const clickable = count > 0
                return (
                  <button
                    key={variant}
                    type="button"
                    disabled={!clickable}
                    onClick={() => onSelectVariant(variant)}
                    title={clickable ? `See ${count} job${count === 1 ? '' : 's'} matching "${variant}"` : 'No jobs currently match this variant'}
                    className={
                      clickable
                        ? 'rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink hover:border-ember hover:text-ember'
                        : 'cursor-default rounded-full border border-line bg-paper/60 px-3 py-1 text-xs font-medium text-ink-soft/60'
                    }
                  >
                    {variant} ({count})
                  </button>
                )
              })}
        </div>
      )}

      {filters.title && (
        <p className="mt-2 text-xs text-ink-soft">
          Match % is based on how closely each job's title and description match your search.
        </p>
      )}
    </div>
  )
}