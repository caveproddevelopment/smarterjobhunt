const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

// One GET /api/geo per page load: the country list for the dropdowns plus
// the backend's guess from the visitor's IP (null behind a VPN/proxy).
let geoPromise = null

export function fetchGeo() {
  if (!geoPromise) {
    geoPromise = fetch(`${API_URL}/api/geo`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('geo lookup failed'))))
      .catch(() => {
        geoPromise = null // let a later call retry
        return { suggested_country: null, is_vpn: false, countries: [] }
      })
  }
  return geoPromise
}
