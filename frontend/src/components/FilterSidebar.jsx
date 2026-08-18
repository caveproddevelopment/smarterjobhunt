export default function FilterSidebar({
  filters,
  onFilterChange,
  onUpdateListings,
  onCompanyDb = () => {},
  savedSearches,
  onApplySearch,
  onDeleteSearch,
  loggedIn = true,
  selectedStatus = null,
  onSelectStatus = () => {},
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

      <div className="mt-4">
        <p className="text-sm text-ink">Company Database</p>
        <div className="mt-1.5 space-y-1.5">
          <label className="flex items-center gap-1.5 text-sm text-ink">
            <input
              type="radio"
              name="company-type"
              checked={(filters.companyType || 'funded') === 'funded'}
              onChange={() => onFilterChange({ ...filters, companyType: 'funded' })}
            />
            Funded Startups
          </label>
          <label className="flex items-center gap-1.5 text-sm text-ink">
            <input
              type="radio"
              name="company-type"
              checked={filters.companyType === 'fortune500'}
              onChange={() => onFilterChange({ ...filters, companyType: 'fortune500' })}
            />
            Fortune 500
          </label>
          <label className="flex items-center gap-1.5 text-sm text-ink">
            <input
              type="radio"
              name="company-type"
              checked={filters.companyType === 'both'}
              onChange={() => onFilterChange({ ...filters, companyType: 'both' })}
            />
            Both
          </label>
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

      {loggedIn && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="text-sm font-medium text-ink">Track Applications</p>
          <p className="mt-1 text-xs text-ink-soft">
            Shows every job you've marked, across all searches — not just the current filters.
          </p>
          <div className="mt-2 space-y-1.5">
            <label className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="radio"
                name="status-filter"
                checked={selectedStatus === 'applied'}
                onChange={() => onSelectStatus('applied')}
              />
              Applied
            </label>
            <label className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="radio"
                name="status-filter"
                checked={selectedStatus === 'rejected'}
                onChange={() => onSelectStatus('rejected')}
              />
              Rejected
            </label>
            <label className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="radio"
                name="status-filter"
                checked={selectedStatus == null}
                onChange={() => onSelectStatus(null)}
              />
              All
            </label>
          </div>
        </div>
      )}

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