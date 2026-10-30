import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { trackCompleteRegistration, trackGoogleAuthLead } from './pixel'
import CountryPromptModal from '../components/CountryPromptModal'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'
const TOKEN_KEY = 'sjh_token'

const AuthContext = createContext(null)

async function parseErrorOr(res, fallback) {
  const body = await res.json().catch(() => null)
  return body?.error || fallback
}

// Razorpay Checkout (users in India) is a script-loaded modal rather than a
// redirect like Stripe's. Loaded on demand, only for Razorpay users.
let razorpayScript = null
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve()
  if (!razorpayScript) {
    razorpayScript = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://checkout.razorpay.com/v1/checkout.js'
      script.onload = resolve
      script.onerror = () => {
        razorpayScript = null
        reject(new Error('Could not load Razorpay. Check your connection and try again.'))
      }
      document.body.appendChild(script)
    })
  }
  return razorpayScript
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const tokenRef = useRef(token)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(token))
  const [sessionMessage, setSessionMessage] = useState(null)
  // Set while startCheckout() is waiting for the user to pick a country.
  const [countryPrompt, setCountryPrompt] = useState(null)

  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error('Session expired')
        return res.json()
      })
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        tokenRef.current = null
        setToken(null)
        setUser(null)
        setSessionMessage('Your session has expired. Please log in again.')
      })
      .finally(() => setLoading(false))
  }, [token])

  // Registration now logs the account straight in (same {token, user}
  // shape as login/loginWithGoogle below) so the caller can immediately
  // chain into startCheckout() -- see Login.jsx, which sends every new
  // signup into Stripe Checkout for the weekly plan's 7-day free trial
  // right after this resolves. The account is still unverified by email
  // at this point; that no longer blocks using the app.
  async function register(fullName, email, password, country) {
    const res = await fetch(`${API_URL}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name: fullName, email, password, country }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not create account'))
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.token)
    tokenRef.current = data.token
    setToken(data.token)
    setUser(data.user)
    trackCompleteRegistration()
    return data
  }

  async function login(email, password) {
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      const err = new Error(body?.error || 'Could not log in')
      err.code = body?.code
      throw err
    }
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.token)
    tokenRef.current = data.token
    setToken(data.token)
    setUser(data.user)
    return data
  }

  // credential is the ID token Google's Sign in with Google button hands
  // back via GoogleSignInButton's onCredential callback. Logs in if this
  // Google account is already linked to a user, links Google to a matching
  // password account, or creates a brand-new account -- backend decides
  // which; either way it comes back in the same {token, user} shape as
  // login() above.
  async function loginWithGoogle(credential) {
    const res = await fetch(`${API_URL}/api/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not sign in with Google'))
    const data = await res.json()
    localStorage.setItem(TOKEN_KEY, data.token)
    tokenRef.current = data.token
    setToken(data.token)
    setUser(data.user)
    trackGoogleAuthLead()
    return data
  }

  async function resendVerification(email) {
    const res = await fetch(`${API_URL}/api/auth/resend-verification`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    const data = await res.json().catch(() => ({}))
    return data.message || 'If that email has a pending account, a verification link has been sent.'
  }

  async function forgotPassword(email) {
    const res = await fetch(`${API_URL}/api/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    const data = await res.json().catch(() => ({}))
    return data.message || 'If that email has an account, a password reset link has been sent.'
  }

  async function resetPassword(token, password) {
    const res = await fetch(`${API_URL}/api/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, password }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not reset password'))
    return res.json() // { message }
  }

  async function updateDefaultFilters({ title, postedDays }) {
    const res = await fetch(`${API_URL}/api/preferences`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        job_title: title || null,
        posted_within_days: postedDays || null,
      }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not save default filters'))
    const updated = await res.json()
    setUser((prev) => (prev ? { ...prev, ...updated } : prev))
    return updated
  }

  async function updateProfile(fullName, email) {
    const res = await fetch(`${API_URL}/api/auth/me`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ full_name: fullName, email }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not update profile'))
    const updated = await res.json()
    setUser((prev) => (prev ? { ...prev, ...updated } : prev))
    return updated
  }

  // Backs out of a pending email change started by updateProfile() above --
  // clears pending_email server-side so the confirmation link, if clicked
  // later, is treated as stale.
  async function cancelEmailChange() {
    const res = await fetch(`${API_URL}/api/auth/me/cancel-email-change`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not cancel email change'))
    const updated = await res.json()
    setUser((prev) => (prev ? { ...prev, ...updated } : prev))
    return updated
  }

  async function refreshUser() {
    if (!token) return
    const res = await fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return
    setUser(await res.json())
  }

  // Resolves with the country the user picks in CountryPromptModal, or
  // null if they cancel.
  function askForCountry() {
    return new Promise((resolve) => setCountryPrompt({ resolve }))
  }

  // interval is 'week' (the only plan offered). The backend picks the
  // payment provider from the user's country: Stripe redirects the whole
  // page to Stripe Checkout (no Stripe.js needed); Razorpay (India) opens
  // Razorpay's checkout modal. Either way the user ends up back on
  // /profile?checkout=success|cancelled, same as before.
  async function startCheckout(
    interval,
    checkoutToken = tokenRef.current || localStorage.getItem(TOKEN_KEY),
    country = null
  ) {
    if (!checkoutToken) throw new Error('Please sign in again before starting checkout')
    const res = await fetch(`${API_URL}/api/billing/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${checkoutToken}` },
      body: JSON.stringify(country ? { interval, country } : { interval }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      if (body?.code === 'country_required' && !country) {
        const chosen = await askForCountry()
        if (!chosen) throw new Error('Please choose your country to start your free trial.')
        return startCheckout(interval, checkoutToken, chosen)
      }
      throw new Error(body?.error || 'Could not start checkout')
    }
    const data = await res.json()
    if (data.provider === 'razorpay') {
      await openRazorpayCheckout(data, checkoutToken)
      return
    }
    window.location.href = data.url
  }

  async function openRazorpayCheckout(checkout, checkoutToken) {
    await loadRazorpay()
    const razorpay = new window.Razorpay({
      key: checkout.key_id,
      subscription_id: checkout.subscription_id,
      name: 'JobBeggar',
      description: 'Weekly plan — first 7 days free',
      prefill: checkout.prefill,
      theme: { color: '#E24B34' },
      handler: async (response) => {
        // Unlock access right away; the webhook applies the same state
        // again, so a failed call here only delays it.
        await fetch(`${API_URL}/api/billing/razorpay/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${checkoutToken}` },
          body: JSON.stringify(response),
        }).catch(() => {})
        window.location.href = '/profile?checkout=success'
      },
      modal: {
        ondismiss: () => {
          window.location.href = '/profile?checkout=cancelled'
        },
      },
    })
    razorpay.open()
  }

  // Razorpay has no hosted billing portal, so Razorpay subscribers cancel
  // from the Profile page through this instead of openBillingPortal().
  async function cancelRazorpaySubscription() {
    const res = await fetch(`${API_URL}/api/billing/razorpay/cancel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not cancel subscription'))
    const updated = await res.json()
    setUser((prev) => (prev ? { ...prev, ...updated } : prev))
    return updated
  }

  // Redirects to Stripe's hosted billing portal, where the user can switch
  // plans, update their card, or cancel.
  async function openBillingPortal() {
    const res = await fetch(`${API_URL}/api/billing/portal`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not open billing portal'))
    const { url } = await res.json()
    window.location.href = url
  }

  async function changePassword(currentPassword, newPassword) {
    const res = await fetch(`${API_URL}/api/auth/me/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not change password'))
    return res.json()
  }

  async function logout() {
    if (token) {
      await fetch(`${API_URL}/api/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {})
    }
    localStorage.removeItem(TOKEN_KEY)
    tokenRef.current = null
    setToken(null)
    setUser(null)
  }

  function clearSessionMessage() {
    setSessionMessage(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        register,
        login,
        loginWithGoogle,
        logout,
        updateProfile,
        cancelEmailChange,
        changePassword,
        updateDefaultFilters,
        refreshUser,
        startCheckout,
        openBillingPortal,
        cancelRazorpaySubscription,
        resendVerification,
        forgotPassword,
        resetPassword,
        sessionMessage,
        clearSessionMessage,
      }}
    >
      {children}
      {countryPrompt && (
        <CountryPromptModal
          onSubmit={(country) => {
            countryPrompt.resolve(country)
            setCountryPrompt(null)
          }}
          onCancel={() => {
            countryPrompt.resolve(null)
            setCountryPrompt(null)
          }}
        />
      )}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside an AuthProvider')
  return ctx
}