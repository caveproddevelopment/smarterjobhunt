import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import PasswordInput from '../components/PasswordInput'
import { useAuth } from '../lib/auth'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const { resetPassword } = useAuth()

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      await resetPassword(token, password)
      setDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto flex max-w-md flex-col px-6 pb-24 pt-8">
          {!token ? (
            <>
              <h1 className="font-display text-2xl font-semibold text-ink">Invalid reset link</h1>
              <p className="mt-3 text-sm text-ink-soft">
                This password reset link is missing its token. Request a new one from the login
                page.
              </p>
              <Link
                to="/login"
                className="mt-6 w-full rounded-full flame-gradient px-5 py-2.5 text-center text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
              >
                Back to log in
              </Link>
            </>
          ) : done ? (
            <>
              <h1 className="font-display text-2xl font-semibold text-ink">Password updated</h1>
              <p className="mt-3 text-sm text-ink-soft">
                Your password has been changed. You can log in with your new password now.
              </p>
              <Link
                to="/login"
                className="mt-6 w-full rounded-full flame-gradient px-5 py-2.5 text-center text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
              >
                Log in
              </Link>
            </>
          ) : (
            <>
              <h1 className="font-display text-2xl font-semibold text-ink">Set a new password</h1>
              <p className="mt-2 text-sm text-ink-soft">
                Reset links expire 5 minutes after they're sent, so if this fails, just request a
                new one from the login page.
              </p>

              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                <div>
                  <label htmlFor="password" className="text-sm font-medium text-ink">
                    New password
                  </label>
                  <div className="mt-2">
                    <PasswordInput
                      id="password"
                      required
                      minLength={8}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </div>
                  <p className="mt-1 text-xs text-ink-soft">At least 8 characters.</p>
                </div>

                <div>
                  <label htmlFor="confirmPassword" className="text-sm font-medium text-ink">
                    Confirm new password
                  </label>
                  <div className="mt-2">
                    <PasswordInput
                      id="confirmPassword"
                      required
                      minLength={8}
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                    />
                  </div>
                </div>

                {error && <p className="text-sm text-ember">{error}</p>}

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
                >
                  {submitting ? 'Please wait…' : 'Update password'}
                </button>
              </form>
            </>
          )}
        </main>

        <Footer />
      </div>
    </div>
  )
}
