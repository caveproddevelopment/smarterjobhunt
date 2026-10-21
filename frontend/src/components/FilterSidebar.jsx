import { COMPANY_TYPE_FILTER_OPTIONS } from '../lib/companyTypes'
import { DEFAULT_RADIUS_MILES } from '../lib/api'
import PostedDaysPicker from './PostedDaysPicker'

// Distance slider range, in miles. The backend caps radius_miles at 500 too.
const MIN_RADIUS = 5
const MAX_RADIUS = 500
const RADIUS_STEP = 5

export default function FilterSidebar({
  filters,
  onFilterChange,
  onUpdateListings,
  savedSearches,
  onApplySearch,
  onDeleteSearch,
  loggedIn = true,
  selectedStatus = null,
  onSelectStatus = () => {},
  companyTypeCounts = {},
  companyTypeCountsLoading = false,
  // Shown under the Job Title box when Update Search is clicked without one.
  titleError = null,
}) {
  const hasLocation = Boolean((filters.location || '').trim())
  const radius = filters.radiusMiles ?? DEFAULT_RADIUS_MILES

  // Small count label shown next to a Company Database option: plain
  // ink text (not ember) once we know the count, muted while the fetch
  // for the current title/postedDays search is still in flight.
  function renderCount(key) {
    const count = companyTypeCounts[key]
    const countKnown = typeof count === 'number'
    if (countKnown) {
      return <span className="text-ink">{count} jobs</span>
    }
    if (companyTypeCountsLoading) {
      return <span className="text-ink-soft/50">…</span>
    }
    return null
  }

  return (
    <aside className="w-full">
      <h2 className="text-sm font-semibold text-ink">Search Panel</h2>

      <div className="mt-4 flex items-center gap-2">
        <label htmlFor="filter-title" className="shrink-0 text-sm text-ink">
          Job Title
        </label>
        <input
          id="filter-title"
          type="text"
          value={filters.title}
          placeholder="Required"
          required
          aria-invalid={Boolean(titleError)}
          aria-describedby={titleError ? 'filter-title-error' : undefined}
          onChange={(event) => onFilterChange({ ...filters, title: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Enter') onUpdateListings()
          }}
          className={`min-w-0 flex-1 border px-2 py-1.5 text-sm text-ink placeholder:text-ink-soft/60 focus:outline-none ${
            titleError ? 'border-ember focus:border-ember' : 'border-line focus:border-ink-soft'
          }`}
        />
      </div>
      {titleError && (
        <p id="filter-title-error" className="mt-1 text-xs text-ember">
          {titleError}
        </p>
      )}

      <div className="mt-3">
        <p className="text-sm text-ink">Posted in the last</p>
        <div className="mt-1.5">
          <PostedDaysPicker
            id="filter-days"
            value={filters.postedDays}
            onChange={(postedDays) => onFilterChange({ ...filters, postedDays })}
          />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <label htmlFor="filter-location" className="shrink-0 text-sm text-ink">
          Location
        </label>
        <input
          id="filter-location"
          type="text"
          value={filters.location || ''}
          placeholder="City, state or country"
          onChange={(event) => onFilterChange({ ...filters, location: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === 'Enter') onUpdateListings()
          }}
          className="min-w-0 flex-1 border border-line px-2 py-1.5 text-sm text-ink placeholder:text-ink-soft/60 focus:border-ink-soft focus:outline-none"
        />
      </div>

      <div className={`mt-2 ${hasLocation ? '' : 'opacity-50'}`}>
        <div className="flex items-center justify-between text-sm text-ink">
          <label htmlFor="filter-radius">Distance</label>
          <span className="font-medium">Within {radius} mi</span>
        </div>
        <input
          id="filter-radius"
          type="range"
          min={MIN_RADIUS}
          max={MAX_RADIUS}
          step={RADIUS_STEP}
          value={radius}
          disabled={!hasLocation}
          onChange={(event) => onFilterChange({ ...filters, radiusMiles: Number(event.target.value) })}
          className="mt-1 w-full accent-ember disabled:cursor-not-allowed"
        />
        <div className="flex justify-between text-[11px] text-ink-soft">
          <span>{MIN_RADIUS} mi</span>
          <span>{MAX_RADIUS} mi</span>
        </div>
        <p className="mt-1 text-xs text-ink-soft">
          {hasLocation ? 'Remote jobs are always included.' : 'Type a location to use the distance slider.'}
        </p>
      </div>

      <div className="mt-4">
        <p className="text-sm text-ink">Companies</p>
        <div className="mt-1.5 space-y-2">
          {COMPANY_TYPE_FILTER_OPTIONS.map(({ value, label }) => {
            const count = renderCount(value)
            return (
              <label key={value} className="flex items-start gap-1.5 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={(filters.companyTypes || []).includes(value)}
                  onChange={(event) => {
                    const companyTypes = filters.companyTypes || []
                    if (event.target.checked) {
                      onFilterChange({ ...filters, companyTypes: [...companyTypes, value] })
                    } else {
                      onFilterChange({ ...filters, companyTypes: companyTypes.filter((t) => t !== value) })
                    }
                  }}
                  className="mt-0.5 shrink-0"
                />
                <span>
                  {label}
                  {count && <> - {count}</>}
                </span>
              </label>
            )
          })}
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between text-sm text-ink">
        <span>Remote Only</span>
        <input
          type="checkbox"
          checked={Boolean(filters.remoteOnly)}
          onChange={(event) => onFilterChange({ ...filters, remoteOnly: event.target.checked })}
          className="h-4 w-4 accent-ember"
        />
      </div>

      <button
        type="button"
        onClick={onUpdateListings}
        className="mt-4 block w-full rounded-full flame-gradient py-2 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.02]"
      >
        Update Search
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
                checked={selectedStatus === 'neither'}
                onChange={() => onSelectStatus('neither')}
              />
              Neither
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