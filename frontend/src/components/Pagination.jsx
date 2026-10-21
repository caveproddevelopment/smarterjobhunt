// Page numbers with Prev/Next, e.g. ‹ Prev 1 … 4 5 6 … 12 Next ›.
function pageItems(page, totalPages) {
  const pages = new Set([1, totalPages, page - 1, page, page + 1])
  const sorted = [...pages].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b)
  const items = []
  for (let i = 0; i < sorted.length; i += 1) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) items.push(`gap-${sorted[i]}`)
    items.push(sorted[i])
  }
  return items
}

export default function Pagination({ page, totalPages, onPageChange }) {
  if (totalPages <= 1) return null
  const navButton =
    'rounded-full px-3 py-1.5 text-sm font-medium text-ink hover:bg-mist disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'

  return (
    <nav aria-label="Job list pages" className="flex flex-wrap items-center justify-center gap-1 border-t border-line px-4 py-4">
      <button type="button" className={navButton} disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        ‹ Prev
      </button>
      {pageItems(page, totalPages).map((item) =>
        typeof item === 'string' ? (
          <span key={item} className="px-1 text-sm text-ink-soft">
            …
          </span>
        ) : (
          <button
            key={item}
            type="button"
            aria-current={item === page ? 'page' : undefined}
            onClick={() => onPageChange(item)}
            className={`min-w-9 rounded-full px-3 py-1.5 text-sm font-medium ${
              item === page ? 'flame-gradient text-white' : 'text-ink hover:bg-mist'
            }`}
          >
            {item}
          </button>
        ),
      )}
      <button
        type="button"
        className={navButton}
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Next ›
      </button>
    </nav>
  )
}
