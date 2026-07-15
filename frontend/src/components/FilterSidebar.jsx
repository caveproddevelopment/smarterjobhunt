import { useState } from 'react'
import PillRadioGroup from './PillRadioGroup'

export default function FilterSidebar({
  filters,
  onFilterChange,
  onUpdateListings,
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
    <aside className="w-full shrink-0 rounded-2xl border border-line bg-white p-6 md:w-72">
      <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-ink-soft">
        Search criteria &amp; filters
      </h2>

      <div className="mt-5">
        <label htmlFor="filter-title" className="text-sm font-medium text-ink">
          Job title
        </label>
        <input
          id="filter-title"
          type="text"
          value={filters.title}
          onChange={(event) => onFilterChange({ ...filters, title: event.target.value })}
          placeholder="e.g. Product Manager"
          className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
        />
      </div>

      <div className="mt-5">
        <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
          Variants
          <span
            title="How many close variants of this title to include, e.g. 'PM' or 'Sr. PM'"
            className="flex h-4 w-4 items-center justify-center rounded-full bg-mist text-[10px] font-semibold text-ink-soft"
          >
            i
          </span>
        </p>
        <div className="mt-2">
          <PillRadioGroup
            name="Variants"
            value={filters.variants}
            onChange={(value) => onFilterChange({ ...filters, variants: value })}
            options={[
              { value: 5, label: '5' },
              { value: 10, label: '10' },
              { value: 15, label: '15' },
            ]}
          />
        </div>
      </div>

      <div className="mt-5">
        <label htmlFor="filter-days" className="text-sm font-medium text-ink">
          Posted in the last
        </label>
        <div className="mt-2 flex items-center gap-2">
          <input
            id="filter-days"
            type="number"
            min="0"
            value={filters.postedDays}
            onChange={(event) =>
              onFilterChange({ ...filters, postedDays: event.target.value })
            }
            className="w-20 rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
          />
          <span className="text-sm text-ink-soft">days</span>
        </div>
      </div>

      <div className="mt-5">
        <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
          Limit funding
          <span
            title="Filter to companies at a specific funding stage"
            className="flex h-4 w-4 items-center justify-center rounded-full bg-mist text-[10px] font-semibold text-ink-soft"
          >
            i
          </span>
        </p>
        <div className="mt-2">
          <PillRadioGroup
            name="Limit funding"
            value={filters.funding}
            onChange={(value) => onFilterChange({ ...filters, funding: value })}
            options={[
              { value: 'both', label: 'Both' },
              { value: 'a', label: 'A only' },
              { value: 'b', label: 'B only' },
            ]}
          />
        </div>
      </div>

      <button
        type="button"
        onClick={onUpdateListings}
        className="mt-6 w-full rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
      >
        Update listings
      </button>

      <div className="mt-8 border-t border-line pt-6">
        <label htmlFor="search-name" className="text-sm font-medium text-ink">
          Search name
        </label>
        {!loggedIn && (
          <p className="mt-1 text-xs text-ink-soft">Log in to save searches across visits.</p>
        )}
        <div className="mt-2 flex gap-2">
          <input
            id="search-name"
            type="text"
            value={searchName}
            onChange={(event) => setSearchName(event.target.value)}
            placeholder="e.g. Remote PM roles"
            className="w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSave}
            className="shrink-0 rounded-lg border border-line px-3 py-2 text-sm font-medium text-ink hover:border-ink-soft/40"
          >
            Save
          </button>
        </div>
      </div>

      <div className="mt-6">
        <p className="text-sm font-medium text-ink">Your saved searches</p>
        {savedSearches.length === 0 ? (
          <p className="mt-2 text-xs text-ink-soft">
            Nothing saved yet — save a search above to find it here later.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
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
                  className="text-ink underline decoration-line underline-offset-2 hover:text-ember"
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
