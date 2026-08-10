import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import PasswordInput from '../components/PasswordInput'
import { useAuth } from '../lib/auth'

export default function Profile() {
  const {
    user,
    loading,
    logout,
    updateProfile,
    changePassword,
    refreshUser,
    startCheckout,
    openBillingPortal,
  } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const checkoutStatus = searchParams.get('checkout')

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [profileError, setProfileError] = useState(null)
  const [profileSuccess, setProfileSuccess] = useState(null)
  const [savingProfile, setSavingProfile] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState(null)
  const [passwordSuccess, setPasswordSuccess] = useState(null)
  const [savingPassword, setSavingPassword] = useState(false)

  const [billingLoading, setBillingLoading] = useState(false)
  const [billingError, setBillingError] = useState(null)

  // Not logged in (and we're done checking) -> bounce to login.
  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [loading, user, navigate])

  // Coming back from a successful Stripe Checkout — the webhook that flips
  // `plan` to 'pro' usually lands within a second or two, so refresh once
  // right away and once more shortly after to pick it up.
  useEffect(() => {
    if (checkoutStatus === 'success') {
      refreshUser()
      const timer = setTimeout(refreshUser, 2000)
      return () => clearTimeout(timer)
    }
  }, [checkoutStatus, refreshUser])

  // Seed the form fields once we have a user.
  useEffect(() => {
    if (user) {
      setFullName(user.full_name || '')
      setEmail(user.email || '')
    }
  }, [user])

  function handleLogout() {
    logout()
    navigate('/')
  }

  async function handleProfileSubmit(event) {
    event.preventDefault()
    setProfileError(null)
    setProfileSuccess(null)
    setSavingProfile(true)
    try {
      await updateProfile(fullName, email)
      setProfileSuccess('Profile updated.')
    } catch (err) {
      setProfileError(err.message)
    } finally {
      setSavingProfile(false)
    }
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault()
    setPasswordError(null)
    setPasswordSuccess(null)

    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match')
      return
    }

    setSavingPassword(true)
    try {
      await changePassword(currentPassword, newPassword)
      setPasswordSuccess('Password updated.')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setPasswordError(err.message)
    } finally {
      setSavingPassword(false)
    }
  }

  async function handleSubscribe(interval) {
    setBillingError(null)
    setBillingLoading(true)
    try {
      await startCheckout(interval) // redirects the page to Stripe on success
    } catch (err) {
      setBillingError(err.message)
      setBillingLoading(false)
    }
  }

  async function handleManageBilling() {
    setBillingError(null)
    setBillingLoading(true)
    try {
      await openBillingPortal() // redirects the page to Stripe on success
    } catch (err) {
      setBillingError(err.message)
      setBillingLoading(false)
    }
  }

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-paper">
        <Navbar />
        <main className="mx-auto max-w-2xl px-6 py-24 text-center text-sm text-ink-soft">
          Loading your profile…
        </main>
      </div>
    )
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-2xl px-6 pb-24 pt-8">
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-soft transition-colors hover:text-ink"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4"
              width="16"
              height="16"
            >
              <path d="M19 12H5" />
              <path d="M12 19l-7-7 7-7" />
            </svg>
            Back to job listings
          </Link>

          <h1 className="mt-4 font-display text-2xl font-semibold text-ink">Your profile</h1>
          <p className="mt-2 text-sm text-ink-soft">
            Manage your account details, password, and plan.
          </p>

          {/* Account details */}
          <section className="mt-8 border border-line p-6">
            <h2 className="font-display text-lg font-semibold text-ink">Account details</h2>
            <form onSubmit={handleProfileSubmit} className="mt-4 space-y-4">
              <div>
                <label htmlFor="fullName" className="text-sm font-medium text-ink">
                  Full name
                </label>
                <input
                  id="fullName"
                  type="text"
                  required
                  minLength={2}
                  maxLength={50}
                  pattern="[A-Za-z]+( [A-Za-z]+)*"
                  title="Letters and spaces only"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
                />
                <p className="mt-1 text-xs text-ink-soft">2–50 characters. Letters and spaces only.</p>
              </div>

              <div>
                <label htmlFor="email" className="text-sm font-medium text-ink">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
                />
              </div>

              {profileError && <p className="text-sm text-ember">{profileError}</p>}
              {profileSuccess && <p className="text-sm text-moss">{profileSuccess}</p>}

              <button
                type="submit"
                disabled={savingProfile}
                className="rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
              >
                {savingProfile ? 'Saving…' : 'Save changes'}
              </button>
            </form>
          </section>

          {/* Change password */}
          <section className="mt-8 border border-line p-6">
            <h2 className="font-display text-lg font-semibold text-ink">Change password</h2>
            {user.has_password === false ? (
              <p className="mt-4 text-sm text-ink-soft">
                Your account signs in with Google, so there's no password to change here.
              </p>
            ) : (
              <form onSubmit={handlePasswordSubmit} className="mt-4 space-y-4">
                <div>
                  <label htmlFor="current-password" className="text-sm font-medium text-ink">
                    Current password
                  </label>
                  <div className="mt-2">
                    <PasswordInput
                      id="current-password"
                      required
                      value={currentPassword}
                      onChange={(event) => setCurrentPassword(event.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="new-password" className="text-sm font-medium text-ink">
                    New password
                  </label>
                  <div className="mt-2">
                    <PasswordInput
                      id="new-password"
                      required
                      minLength={8}
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                    />
                  </div>
                  <p className="mt-1 text-xs text-ink-soft">At least 8 characters.</p>
                </div>

                <div>
                  <label htmlFor="confirm-password" className="text-sm font-medium text-ink">
                    Confirm new password
                  </label>
                  <div className="mt-2">
                    <PasswordInput
                      id="confirm-password"
                      required
                      minLength={8}
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                    />
                  </div>
                </div>

                {passwordError && <p className="text-sm text-ember">{passwordError}</p>}
                {passwordSuccess && <p className="text-sm text-moss">{passwordSuccess}</p>}

                <button
                  type="submit"
                  disabled={savingPassword}
                  className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-mist disabled:opacity-60"
                >
                  {savingPassword ? 'Updating…' : 'Update password'}
                </button>
              </form>
            )}
          </section>

          {/* Billing */}
          <section className="mt-8 border border-line p-6">
            <h2 className="font-display text-lg font-semibold text-ink">Billing</h2>

            {checkoutStatus === 'success' && (
              <p className="mt-4 rounded-lg border border-line bg-mist px-3 py-2 text-sm text-moss">
                Subscription confirmed — thanks! This may take a few seconds to update below.
              </p>
            )}
            {checkoutStatus === 'cancelled' && (
              <p className="mt-4 rounded-lg border border-line bg-mist px-3 py-2 text-sm text-ink-soft">
                Checkout cancelled — you weren't charged.
              </p>
            )}
            {billingError && <p className="mt-4 text-sm text-ember">{billingError}</p>}

            <div className="mt-4 flex items-center justify-between gap-4 rounded-lg bg-mist px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-ink">
                  {user.plan === 'pro'
                    ? `Pro plan — billed ${user.billing_interval === 'week' ? 'weekly' : 'monthly'}`
                    : 'Free plan'}
                </p>
                <p className="text-xs text-ink-soft">
                  {user.plan === 'pro'
                    ? user.current_period_end
                      ? `Renews ${new Date(user.current_period_end).toLocaleDateString()}.`
                      : 'You have full access to all features.'
                    : 'Basic access to job listings and saved searches.'}
                </p>
              </div>
              {user.plan === 'pro' && (
                <button
                  type="button"
                  onClick={handleManageBilling}
                  disabled={billingLoading}
                  className="shrink-0 rounded-full border border-line px-4 py-2 text-xs font-semibold text-ink transition-colors hover:bg-paper disabled:opacity-60"
                >
                  {billingLoading ? 'Opening…' : 'Manage subscription'}
                </button>
              )}
            </div>

            {user.plan !== 'pro' && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => handleSubscribe('week')}
                  disabled={billingLoading}
                  className="rounded-lg border border-line px-4 py-3 text-left transition-colors hover:bg-mist disabled:opacity-60"
                >
                  <p className="text-sm font-semibold text-ink">Weekly</p>
                  <p className="text-xs text-ink-soft">Billed every week, cancel anytime.</p>
                </button>
                <button
                  type="button"
                  onClick={() => handleSubscribe('month')}
                  disabled={billingLoading}
                  className="rounded-lg border border-line px-4 py-3 text-left transition-colors hover:bg-mist disabled:opacity-60"
                >
                  <p className="text-sm font-semibold text-ink">Monthly</p>
                  <p className="text-xs text-ink-soft">Billed every month, cancel anytime.</p>
                </button>
              </div>
            )}
          </section>

          {/* Logout */}
          <div className="mt-8">
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-mist"
            >
              Log out
            </button>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}
