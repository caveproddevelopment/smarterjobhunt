// Lightweight Meta (Facebook) Pixel wrapper.
//
// This entirely no-ops if VITE_META_PIXEL_ID isn't set, so it's safe to
// import and call from anywhere even before the env var exists in Vercel.
// Set VITE_META_PIXEL_ID in Vercel's Environment Variables (Production +
// Preview) to the pixel ID from Events Manager to turn this on.
const PIXEL_ID = import.meta.env.VITE_META_PIXEL_ID

let initialized = false

// Loads fbevents.js, initializes the pixel, and fires the first PageView.
// Call once at app startup (see main.jsx). Subsequent client-side route
// changes are handled by trackPageView() below since this is a SPA.
export function initPixel() {
  if (initialized || !PIXEL_ID || typeof window === 'undefined') return
  initialized = true

  /* eslint-disable */
  ;(function (f, b, e, v, n, t, s) {
    if (f.fbq) return
    n = f.fbq = function () {
      n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments)
    }
    if (!f._fbq) f._fbq = n
    n.push = n
    n.loaded = true
    n.version = '2.0'
    n.queue = []
    t = b.createElement(e)
    t.async = true
    t.src = v
    s = b.getElementsByTagName(e)[0]
    s.parentNode.insertBefore(t, s)
  })(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js')
  /* eslint-enable */

  window.fbq('init', PIXEL_ID)
  window.fbq('track', 'PageView')
}

// Fire on every client-side route change after the first (BrowserRouter
// doesn't reload the page, so the pixel's own auto-PageView only covers the
// very first load).
export function trackPageView() {
  if (!PIXEL_ID || typeof window.fbq !== 'function') return
  window.fbq('track', 'PageView')
}

// Fires when a brand-new account is created via the password signup form
// (src/lib/auth.jsx register()). Not fired on plain login -- this is the
// actual "someone completed signup" signal Meta needs to optimize the
// campaign toward real conversions instead of cheap page loads.
export function trackCompleteRegistration(params = {}) {
  if (!PIXEL_ID || typeof window.fbq !== 'function') return
  window.fbq('track', 'CompleteRegistration', params)
}

// Fires on a successful Google sign-in (auth.jsx loginWithGoogle()).
//
// NOTE: the backend's POST /api/auth/google response doesn't currently say
// whether it just created a new account or logged into an existing one --
// loginWithGoogle() gets the same {token, user} shape either way. So this
// is tagged as a softer "Lead" event rather than CompleteRegistration, to
// avoid over-counting returning users as new signups once this app has
// existing users signing back in via Google. If the backend starts
// returning something like `created: true/false`, switch the created===true
// case to trackCompleteRegistration instead.
export function trackGoogleAuthLead(params = {}) {
  if (!PIXEL_ID || typeof window.fbq !== 'function') return
  window.fbq('track', 'Lead', { content_name: 'google_auth', ...params })
}

// Dollar value per billing interval -- kept in sync by hand with the
// backend's Stripe prices (STRIPE_PRICE_WEEKLY / STRIPE_PRICE_MONTHLY in
// config.py). Update here if pricing ever changes.
const PLAN_VALUES = { week: 3.99, month: 9.99 }

// Fires once a Stripe Checkout session has actually completed and the
// webhook has flipped the account to plan='pro' (see Profile.jsx, which
// calls this the moment that happens). This is the real "started paying"
// signal Meta needs to optimize the ad campaign toward -- CompleteRegistration
// and Lead above only mean an account exists, not that anyone paid.
export function trackSubscribe(interval, params = {}) {
  if (!PIXEL_ID || typeof window.fbq !== 'function') return
  window.fbq('track', 'Subscribe', {
    value: PLAN_VALUES[interval],
    currency: 'USD',
    ...params,
  })
}