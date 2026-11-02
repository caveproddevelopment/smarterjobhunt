// The sidebar's Remote dropdown. Values match the backend's `remote`
// parameter on /api/jobs and saved_searches.remote_mode.
export const DEFAULT_REMOTE_MODE = 'include'

export const REMOTE_OPTIONS = [
  { value: 'only', label: 'Remote only' },
  { value: 'include', label: 'Remote included' },
  { value: 'exclude', label: 'No remote jobs' },
]

// Short labels for the Active filters chips and bookmark names. 'include'
// has none: it's the default, so it isn't shown as a filter.
export const REMOTE_CHIP_LABELS = {
  only: 'Remote only',
  exclude: 'No remote jobs',
}

// A saved search (or any older data) -> one of the three modes. Bookmarks
// saved before the dropdown existed only have remote_only.
export function remoteModeOf(value, legacyRemoteOnly = false) {
  if (value === 'only' || value === 'include' || value === 'exclude') return value
  return legacyRemoteOnly ? 'only' : DEFAULT_REMOTE_MODE
}
