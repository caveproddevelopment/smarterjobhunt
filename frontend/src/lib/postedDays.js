// "Posted in the last" choices. The value is what's sent as posted_days
// ('' = no limit). Kept to three fixed options instead of a free number.
export const POSTED_DAYS_OPTIONS = [
  { value: '7', label: '1 week' },
  { value: '14', label: '2 weeks' },
  { value: '', label: 'All' },
]

// Older bookmarks and saved defaults can hold any number of days (e.g. 30).
// Snap them to the nearest option that doesn't hide anything they used to
// show: up to 7 -> 1 week, up to 14 -> 2 weeks, anything longer -> All.
export function normalizePostedDays(value) {
  const days = Number(value)
  if (!value || !Number.isFinite(days) || days <= 0) return ''
  if (days <= 7) return '7'
  if (days <= 14) return '14'
  return ''
}

export function postedDaysLabel(value) {
  return POSTED_DAYS_OPTIONS.find((option) => option.value === normalizePostedDays(value))?.label || 'All'
}
