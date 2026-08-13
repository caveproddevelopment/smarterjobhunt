import { useState } from 'react'

export default function DefaultFiltersModal({ onSave, onSkip, saving }) {
  const [filters, setFilters] = useState({
    title: '',
    postedDays: '',
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-md border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">Set your default filters</h2>
        <p className="mt-1 text-sm text-ink-soft">
          We'll pre-fill Job Listings with these every time you visit. You can change this later
          from the sidebar.
        </p>

        <div className="mt-5">
          <label htmlFor="default-title" className="text-sm text-ink">
            Job Title
          </label>
          <input
            id="default-title"
            type="text"
            value={filters.title}
            onChange={(event) => setFilters({ ...filters, title: event.target.value })}
            placeholder="e.g. Product Manager"
            className="mt-1 block w-full border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
          />
        </div>

        <div className="mt-4">
          <label htmlFor="default-days" className="text-sm text-ink">
            Posted in the last
          </label>
          <div className="mt-1 flex items-center gap-2">
            <input
              id="default-days"
              type="number"
              min="0"
              value={filters.postedDays}
              onChange={(event) => setFilters({ ...filters, postedDays: event.target.value })}
              className="w-16 border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
            />
            <span className="text-sm text-ink">days</span>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3">
          <button
            type="button"
            onClick={onSkip}
            disabled={saving}
            className="flex-1 rounded-full border border-line py-2.5 text-sm font-medium text-ink hover:bg-mist disabled:opacity-60"
          >
            Skip for now
          </button>
          <button
            type="button"
            onClick={() => onSave(filters)}
            disabled={saving}
            className="flex-1 rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02] disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save as my defaults'}
          </button>
        </div>
      </div>
    </div>
  )
}
