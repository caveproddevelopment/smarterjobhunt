export default function FilterSidebar({
  filters,
  onFilterChange,
  onUpdateListings,
  onCompanyDb = () => {},
  savedSearches,
  onApplySearch,
  onDeleteSearch,
  loggedIn = true,
}) {
  return (
    <aside className="w-full shrink-0 border border-line bg-paper p-5 md:w-72">
      <h2 className="text-sm font-semibold text-ink">Search Criteria and Filters</h2>

      <div className="mt-4">
        <label htmlFor="filter-title" className="text-sm text-ink">
          Job Title
        </label>
        <input
          id="filter-title"
          type="text"
          value={filters.title}
          onChange={(event) => onFilterChange({ ...filters, title: event.target.value })}
          className="mt-1 block w-full border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
        />
      </div>

      <div className="mt-4">
        <label htmlFor="filter-days" className="text-sm text-ink">
          Posted in the last
        </label>
        <div className="mt-1 flex items-center gap-2">
          <input
            id="filter-days"
            type="number"
            min="0"
            value={filters.postedDays}
            onChange={(event) => onFilterChange({ ...filters, postedDays: event.target.value })}
            className="w-16 border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
          />
          <span className="text-sm text-ink">days</span>
        </div>
      </div>

      <button
        type="button"
        onClick={onCompanyDb}
        className="mt-5 w-full rounded-md border border-line bg-mist py-2 text-sm font-medium text-ink hover:bg-line/40"
      >
        Company DB
      </button>

      <button
        type="button"
        onClick={onUpdateListings}
        className="mt-3 w-full rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
      >
        Update Listings
      </button>

      <div className="mt-6 border-t border-line pt-5">
        <p className="text-sm font-medium text-ink">Your Bookmarked Searches</p>
        {!loggedIn && (
          <p className="mt-1 text-xs text-ink-soft">Log in to bookmark searches across visits.</p>
        )}
        {savedSearches.length === 0 ? (
          <p className="mt-2 text-xs text-ink-soft">
            Nothing bookmarked yet — click ☆ Bookmark Search above to save your current filters
            here.
          </p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {savedSearches.map((search) => (
              <li key={search.id} className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  onClick={() => onApplySearch(search)}
                  className="text-ember underline decoration-line underline-offset-2 hover:text-flame"
                >
                  {search.name}
                </button>
                <button
                  type="button"
                  onClick={() => onDeleteSearch(search.id)}
                  className="text-xs font-medium text-ember hover:text-flame"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  )
}