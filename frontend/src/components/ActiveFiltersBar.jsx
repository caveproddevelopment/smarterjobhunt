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
  variantCountsError = null,
  onRetryVariantCounts = () => {},
  onSelectVariant = () => {},
  // Job count for whichever view is currently on screen (matches the
  // number shown in the "N Jobs in current search" line above this bar) --
  // shown next to the scoped title once a variant/company/status view is
  // selected, e.g. "Current View: Product Owner (12)".
  scopedCount = null,
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
    const countSuffix =
      typeof scopedCount === 'number' ? ` (${scopedCount} job${scopedCount === 1 ? '' : 's'})` : ''
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
            {countSuffix}
          </span>
        </div>
      </div>
    )
  }

  const restChips = []

  if (filters.postedDays) {
    restChips.push({
      key: 'postedDays',
      label: `Last ${filters.postedDays} days`,
      clear: () => onChange({ ...filters, postedDays: '' }),
    })
  }
  // Display chips for selected company types - multiple types can be selected
  if (filters.companyTypes && filters.companyTypes.length > 0) {
    const companyTypeLabels = filters.companyTypes.map((type) => COMPANY_TYPE_LABELS[type])
    restChips.push({
      key: 'companyTypes',
      label: companyTypeLabels.join(', '),
      clear: () => onChange({ ...filters, companyTypes: [DEFAULT_COMPANY_TYPE] }),
    })
  }
  if (filters.remoteOnly) {
    restChips.push({
      key: 'remoteOnly',
      label: 'Remote',
      clear: () => onChange({ ...filters, remoteOnly: false }),
    })
  }

  const hasTitle = Boolean(filters.title)
  const totalChipCount = restChips.length + (hasTitle ? 1 : 0)
  if (totalChipCount === 0) return null

  const canShowVariants = hasTitle && !titleVariantsLoading && titleVariants.length > 0

  return (
    <div className="border-b border-line bg-mist/60 px-6 py-3">
      <div className="flex flex-wrap items-start gap-2">
        <span className="mt-1.5 text-xs font-medium text-ink-soft">Active filters:</span>

        {hasTitle && (
          // The Title chip and its "See Variants" link/panel are kept in
          // their own stacked column -- the variants UI belongs directly
          // under the Title chip it's about, not centered under the whole
          // filter row.
          <div className="flex flex-col items-center gap-1">
            <span className="flex items-center gap-1.5 rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink">
              <button
                type="button"
                onClick={onJumpToTitleMatch}
                title="Jump to the best-matching job"
                className="hover:text-ember"
              >
                Title: "{filters.title}"
              </button>
              <button
                type="button"
                onClick={() => onChange({ ...filters, title: '' })}
                aria-label="Clear Title filter"
                className="text-ink-soft hover:text-ink"
              >
                ×
              </button>
            </span>

            {canShowVariants && (
              <button
                type="button"
                onClick={onToggleVariants}
                className="text-xs font-semibold text-ember hover:text-flame"
              >
                See Variants
              </button>
            )}

            {showVariants && (
              // Backdrop -- clicking anywhere outside the popup card closes
              // it, same as the × button. stopPropagation on the card below
              // keeps clicks inside (including on a variant pill) from
              // bubbling up and closing it first.
              <div
                className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4"
                onClick={onToggleVariants}
              >
                <div
                  onClick={(event) => event.stopPropagation()}
                  className="w-full max-w-md border border-line bg-paper p-6 shadow-xl"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h2 className="font-display text-lg font-semibold text-ink">
                        Title Variants
                      </h2>
                      <p className="mt-1 text-sm text-ink-soft">
                        Your searched title plus its {titleVariants.length} closest variants.
                        Click one to see just those jobs.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={onToggleVariants}
                      aria-label="Close"
                      className="shrink-0 text-lg leading-none text-ink-soft hover:text-ink"
                    >
                      ×
                    </button>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-2">
                    {variantCountsError ? (
                      <span className="text-xs text-ember">
                        Couldn't load variant counts ({variantCountsError}).{' '}
                        <button
                          type="button"
                          onClick={onRetryVariantCounts}
                          className="underline hover:text-flame"
                        >
                          Try again
                        </button>
                      </span>
                    ) : variantCountsLoading ? (
                      <span className="text-xs text-ink-soft">Loading variant match counts…</span>
                    ) : (
                      // The original searched title is always item 0, so it
                      // gets its own count too, not just the 15 variants
                      // fetched alongside it -- styled a shade darker
                      // (border-ember/50 bg-ember/5) so it reads as "the
                      // title you typed" rather than just another variant.
                      [filters.title, ...titleVariants].map((variant, index) => {
                        const isOriginal = index === 0
                        const count = variantCounts[variant] ?? 0
                        const clickable = count > 0
                        return (
                          <button
                            key={variant}
                            type="button"
                            disabled={!clickable}
                            onClick={() => onSelectVariant(variant)}
                            title={
                              clickable
                                ? `See ${count} job${count === 1 ? '' : 's'} matching "${variant}"`
                                : 'No jobs currently match this title'
                            }
                            className={
                              clickable
                                ? isOriginal
                                  ? 'rounded-full border border-ember/50 bg-ember/5 px-3 py-1 text-xs font-semibold text-ink hover:border-ember hover:text-ember'
                                  : 'rounded-full border border-line bg-paper px-3 py-1 text-xs font-medium text-ink hover:border-ember hover:text-ember'
                                : 'cursor-default rounded-full border border-line bg-paper/60 px-3 py-1 text-xs font-medium text-ink-soft/60'
                            }
                          >
                            {variant} ({count})
                          </button>
                        )
                      })
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {restChips.map((chip) => (
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

        {totalChipCount > 1 && (
          <button
            type="button"
            onClick={() => onChange(DEFAULT_FILTERS)}
            className="text-xs font-medium text-ember hover:text-flame"
          >
            Clear all
          </button>
        )}
      </div>

      {hasTitle && (
        <p className="mt-2 text-xs text-ink-soft">
          Match % is based on how closely each job's title and description match your search.
        </p>
      )}
    </div>
  )
}