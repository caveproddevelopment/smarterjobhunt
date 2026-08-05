import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import { useAuth } from '../lib/auth'

export default function Profile() {
  const { user, loading, logout, updateProfile, changePassword } = useAuth()
  const navigate = useNavigate()

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

  // Not logged in (and we're done checking) -> bounce to login.
  useEffect(() => {
    if (!loading && !user) navigate('/login')
  }, [loading, user, navigate])

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
          <h1 className="font-display text-2xl font-semibold text-ink">Your profile</h1>
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
            <form onSubmit={handlePasswordSubmit} className="mt-4 space-y-4">
              <div>
                <label htmlFor="current-password" className="text-sm font-medium text-ink">
                  Current password
                </label>
                <input
                  id="current-password"
                  type="password"
                  required
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="new-password" className="text-sm font-medium text-ink">
                  New password
                </label>
                <input
                  id="new-password"
                  type="password"
                  required
                  minLength={8}
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
                />
                <p className="mt-1 text-xs text-ink-soft">At least 8 characters.</p>
              </div>

              <div>
                <label htmlFor="confirm-password" className="text-sm font-medium text-ink">
                  Confirm new password
                </label>
                <input
                  id="confirm-password"
                  type="password"
                  required
                  minLength={8}
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  className="mt-2 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
                />
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
          </section>

          {/* Billing */}
          <section className="mt-8 border border-line p-6">
            <h2 className="font-display text-lg font-semibold text-ink">Billing</h2>
            <div className="mt-4 flex items-center justify-between gap-4 rounded-lg bg-mist px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-ink">
                  {user.plan === 'pro' ? 'Pro plan' : 'Free plan'}
                </p>
                <p className="text-xs text-ink-soft">
                  {user.plan === 'pro'
                    ? 'You have full access to all features.'
                    : 'Basic access to job listings and saved searches.'}
                </p>
              </div>
              <button
                type="button"
                disabled
                title="Billing isn't set up yet"
                className="shrink-0 rounded-full border border-line px-4 py-2 text-xs font-semibold text-ink-soft opacity-60"
              >
                Upgrade — coming soon
              </button>
            </div>
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
