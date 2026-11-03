// Campaign tracking (first touch).
// Links carry tags like ?utm_source=meta&utm_campaign=india_launch&utm_content=date_night.
// People often browse first and register later (or on another page), by which time the
// tags are gone from the URL, so the first tagged visit is saved in localStorage and
// sent with the sign-up. Later visits through a different link never overwrite it.
// Visitors who never arrive with tags send nothing and are stored blank ("direct/other").

const KEY = 'jb_utm'
const FIELDS = ['utm_source', 'utm_campaign', 'utm_content']

const clean = (v) =>
  [...String(v || '')].filter((ch) => ch.charCodeAt(0) > 31 && ch.charCodeAt(0) !== 127).join('').trim().slice(0, 100)

export function captureUtm(search = window.location.search) {
  try {
    if (localStorage.getItem(KEY)) return // first touch wins
    const params = new URLSearchParams(search)
    const found = {}
    for (const f of FIELDS) {
      const v = clean(params.get(f))
      if (v) found[f] = v
    }
    if (Object.keys(found).length) localStorage.setItem(KEY, JSON.stringify(found))
  } catch {
    // storage blocked (private mode etc.) -- tracking is best-effort
  }
}

export function getUtm() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}')
    const out = {}
    for (const f of FIELDS) if (saved[f]) out[f] = clean(saved[f])
    return out
  } catch {
    return {}
  }
}
