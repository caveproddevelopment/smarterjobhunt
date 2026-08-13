const DEFAULT_FILTERS = { title: '', postedDays: '' }

export default function ActiveFiltersBar({
  filters,
  onChange,
  titleVariants = [],
  titleVariantsLoading = false,
}) {
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
  if (chips.length === 0) return null

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
      </div>

      {filters.title && (titleVariantsLoading || titleVariants.length > 0) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line/60 pt-2">
          <span className="text-xs font-medium text-ink-soft">Also matching:</span>
          {titleVariantsLoading ? (
            <span className="text-xs text-ink-soft">Finding related titles…</span>
          ) : (
            titleVariants.map((variant) => (
              <span
                key={variant}
                className="rounded-full border border-line bg-paper px-2 py-0.5 text-xs text-ink-soft"
              >
                {variant}
              </span>
            ))
          )}
        </div>
      )}
    </div>
  )
}