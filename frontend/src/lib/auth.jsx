import { createContext, useContext, useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'
const TOKEN_KEY = 'sjh_token'

const AuthContext = createContext(null)

async function parseErrorOr(res, fallback) {
  const body = await res.json().catch(() => null)
  return body?.error || fallback
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(token))
  const [sessionMessage, setSessionMessage] = useState(null)

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
        setToken(null)
        setUser(null)
        setSessionMessage('Your session has expired. Please log in again.')
      })
      .finally(() => setLoading(false))
  }, [token])

  async function register(fullName, email, password) {
    const res = await fetch(`${API_URL}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ full_name: fullName, email, password }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not create account'))
    return res.json() // { message, user } — account is unverified, no session yet
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
    setToken(data.token)
    setUser(data.user)
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
    setToken(data.token)
    setUser(data.user)
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

  // interval is 'week' or 'month'. Redirects the whole page to Stripe
  // Checkout — there's no need for a Stripe.js dependency for this.
  async function startCheckout(interval) {
    const res = await fetch(`${API_URL}/api/billing/checkout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ interval }),
    })
    if (!res.ok) throw new Error(await parseErrorOr(res, 'Could not start checkout'))
    const { url } = await res.json()
    window.location.href = url
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

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
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
        resendVerification,
        forgotPassword,
        resetPassword,
        sessionMessage,
        clearSessionMessage,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside an AuthProvider')
  return ctx
}