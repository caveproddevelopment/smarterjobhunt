import { useState } from 'react'

export default function FilterSidebar({
  filters,
  onFilterChange,
  onUpdateListings,
  onCompanyDb = () => {},
  savedSearches,
  onSaveSearch,
  onDeleteSearch,
  loggedIn = true,
}) {
  const [searchName, setSearchName] = useState('')

  function handleSave() {
    if (!searchName.trim()) return
    onSaveSearch(searchName.trim())
    setSearchName('')
  }

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
        <p className="flex items-center gap-1.5 text-sm text-ink">
          Variants
          <span
            title="How many close variants of this title to include, e.g. 'PM' or 'Sr. PM'"
            className="flex h-4 w-4 items-center justify-center rounded-full bg-mist text-[10px] font-semibold text-ink-soft"
          >
            i
          </span>
        </p>
        <div className="mt-1 flex items-center gap-4">
          {[5, 10, 15].map((value) => (
            <label key={value} className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="radio"
                name="variants"
                checked={filters.variants === value}
                onChange={() => onFilterChange({ ...filters, variants: value })}
              />
              {value}
            </label>
          ))}
        </div>
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
        <p className="flex items-center gap-1.5 text-sm text-ink">
          Limit Funding
          <span
            title="Filter to companies at a specific funding stage"
            className="flex h-4 w-4 items-center justify-center rounded-full bg-mist text-[10px] font-semibold text-ink-soft"
          >
            i
          </span>
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-4">
          {[
            { value: 'both', label: 'Both' },
            { value: 'a', label: 'A Only' },
            { value: 'b', label: 'B Only' },
          ].map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-sm text-ink">
              <input
                type="radio"
                name="funding"
                checked={filters.funding === option.value}
                onChange={() => onFilterChange({ ...filters, funding: option.value })}
              />
              {option.label}
            </label>
          ))}
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
        <label htmlFor="search-name" className="flex items-center gap-1.5 text-sm text-ink">
          Search Name
          <span
            title="Save your current filters under a name to reuse later"
            className="flex h-4 w-4 items-center justify-center rounded-full bg-mist text-[10px] font-semibold text-ink-soft"
          >
            i
          </span>
        </label>
        {!loggedIn && (
          <p className="mt-1 text-xs text-ink-soft">Log in to save searches across visits.</p>
        )}
        <div className="mt-1 flex gap-2">
          <input
            id="search-name"
            type="text"
            value={searchName}
            onChange={(event) => setSearchName(event.target.value)}
            className="w-full border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSave}
            className="shrink-0 rounded-md border border-line bg-mist px-3 py-1.5 text-sm font-medium text-ink hover:bg-line/40"
          >
            Save Search
          </button>
        </div>
      </div>

      <div className="mt-5">
        <p className="text-sm font-medium text-ink">Your Saved Searches</p>
        {savedSearches.length === 0 ? (
          <p className="mt-2 text-xs text-ink-soft">
            Nothing saved yet — save a search above to find it here later.
          </p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {savedSearches.map((search) => (
              <li key={search.id} className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  onClick={() =>
                    onFilterChange({
                      title: search.job_title || '',
                      variants: search.variants || 10,
                      postedDays: search.posted_within_days || '',
                      funding: search.funding_filter || 'both',
                    })
                  }
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