const DEFAULT_FILTERS = { title: '', postedDays: '' }

export default function ActiveFiltersBar({
  filters,
  onChange,
  titleVariants = [],
  titleVariantsLoading = false,
  variantCounts = {},
  variantCountsLoading = false,
  selectedVariant = null,
  onSelectVariant = () => {},
  bookmarked = false,
  onToggleBookmark = () => {},
}) {
  const bookmarkButtonEl = (
    <button
      type="button"
      onClick={onToggleBookmark}
      className="ml-auto flex shrink-0 items-center gap-1.5 text-xs font-medium text-ink-soft hover:text-ink"
    >
      <span aria-hidden="true" className={bookmarked ? 'text-ember' : 'text-ink-soft'}>
        {bookmarked ? '★' : '☆'}
      </span>
      Bookmark Search
    </button>
  )

  // Once a variant pill is selected, the listing is scoped to just that
  // title — the broader "Active filters" chips and "Also matching" pills
  // no longer describe what's showing, so hide both entirely and leave
  // only the bookmark control (which now tracks the variant, not the
  // original search title).
  if (selectedVariant) {
    return (
      <div className="border-b border-line bg-mist/60 px-6 py-3">
        <div className="flex items-center">{bookmarkButtonEl}</div>
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

  // "Also matching" (title variants) renders below the active-filter chips
  // whenever a title is set. The bookmark button always lands on whichever
  // row is currently the last one in the box, right-aligned.
  const showVariants = Boolean(filters.title) && (titleVariantsLoading || titleVariants.length > 0)
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
        {!showVariants && bookmarkButton}
      </div>

      {showVariants && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line/60 pt-2">
          <span className="text-xs font-medium text-ink-soft">Also matching:</span>
          {titleVariantsLoading ? (
            <span className="text-xs text-ink-soft">Finding related titles…</span>
          ) : (
            titleVariants.map((variant) => {
              const count = variantCounts[variant]
              const countKnown = typeof count === 'number'
              const clickable = countKnown && count > 0
              const isActive = selectedVariant === variant

              let pillClasses =
                'flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors '
              if (isActive) {
                pillClasses += 'border-ember bg-ember text-white'
              } else if (clickable) {
                pillClasses +=
                  'border-line bg-paper text-ink hover:border-ember hover:text-ember cursor-pointer'
              } else {
                pillClasses += 'border-line bg-paper text-ink-soft/60 cursor-default'
              }

              return (
                <button
                  key={variant}
                  type="button"
                  disabled={!clickable}
                  onClick={() => onSelectVariant(variant)}
                  title={
                    clickable
                      ? `Show only "${variant}" jobs`
                      : countKnown
                        ? 'No jobs match this title yet'
                        : undefined
                  }
                  className={pillClasses}
                >
                  {variant}
                  {countKnown && (
                    <span
                      className={
                        isActive
                          ? 'text-white/80'
                          : clickable
                            ? 'font-semibold text-ember'
                            : 'text-ink-soft/50'
                      }
                    >
                      {count}
                    </span>
                  )}
                  {!countKnown && variantCountsLoading && (
                    <span className="text-ink-soft/50">…</span>
                  )}
                </button>
              )
            })
          )}
          {bookmarkButton}
        </div>
      )}
    </div>
  )
}