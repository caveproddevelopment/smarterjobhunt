const FUNDING_LABELS = {
  both: 'Both fundings',
  a: 'Series A only',
  b: 'Series B only',
}

const DEFAULT_FILTERS = { title: '', variants: 10, postedDays: '', funding: 'both' }

export default function ActiveFiltersBar({ filters, onChange }) {
  const chips = []

  if (filters.title) {
    chips.push({
      key: 'title',
      label: `Title: "${filters.title}"`,
      clear: () => onChange({ ...filters, title: '' }),
    })
  }
  if (filters.variants !== 10) {
    chips.push({
      key: 'variants',
      label: `${filters.variants} variants`,
      clear: () => onChange({ ...filters, variants: 10 }),
    })
  }
  if (filters.postedDays) {
    chips.push({
      key: 'postedDays',
      label: `Last ${filters.postedDays} days`,
      clear: () => onChange({ ...filters, postedDays: '' }),
    })
  }
  if (filters.funding !== 'both') {
    chips.push({
      key: 'funding',
      label: FUNDING_LABELS[filters.funding],
      clear: () => onChange({ ...filters, funding: 'both' }),
    })
  }

  if (chips.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-mist/60 px-6 py-3">
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
  )
}
