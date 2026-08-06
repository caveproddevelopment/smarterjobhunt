import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import PasswordInput from '../components/PasswordInput'
import { useAuth } from '../lib/auth'

export default function Login() {
  const [searchParams] = useSearchParams()
  const [mode, setMode] = useState('login') // 'login' | 'register' | 'forgot'
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [errorCode, setErrorCode] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [pendingVerificationEmail, setPendingVerificationEmail] = useState(null)
  const [pendingResetEmail, setPendingResetEmail] = useState(null)
  const [resendStatus, setResendStatus] = useState(null)
  const { login, register, resendVerification, forgotPassword, sessionMessage, clearSessionMessage } =
    useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    return () => clearSessionMessage()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setErrorCode(null)
    setSubmitting(true)
    try {
      if (mode === 'login') {
        await login(email, password)
        navigate('/dashboard')
      } else if (mode === 'register') {
        await register(fullName, email, password)
        setPendingVerificationEmail(email)
      } else {
        await forgotPassword(email)
        setPendingResetEmail(email)
      }
    } catch (err) {
      setError(err.message)
      setErrorCode(err.code || null)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResend() {
    setResendStatus('sending')
    const message = await resendVerification(email)
    setResendStatus(message)
  }

  if (pendingVerificationEmail) {
    return (
      <div className="min-h-screen flame-gradient">
        <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
          <Navbar />
          <main className="mx-auto flex max-w-md flex-col px-6 pb-24 pt-8">
            <h1 className="font-display text-2xl font-semibold text-ink">Check your email</h1>
            <p className="mt-3 text-sm text-ink-soft">
              We sent a verification link to <strong>{pendingVerificationEmail}</strong>. Click it
              to activate your account, then come back and log in.
            </p>
            <button
              type="button"
              onClick={() => {
                setMode('login')
                setPendingVerificationEmail(null)
              }}
              className="mt-6 w-full rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
            >
              Back to log in
            </button>
          </main>
          <Footer />
        </div>
      </div>
    )
  }

  if (pendingResetEmail) {
    return (
      <div className="min-h-screen flame-gradient">
        <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
          <Navbar />
          <main className="mx-auto flex max-w-md flex-col px-6 pb-24 pt-8">
            <h1 className="font-display text-2xl font-semibold text-ink">Check your email</h1>
            <p className="mt-3 text-sm text-ink-soft">
              If <strong>{pendingResetEmail}</strong> has an account, we sent a link to reset the
              password. It expires in 5 minutes, so use it soon.
            </p>
            <button
              type="button"
              onClick={() => {
                setMode('login')
                setPendingResetEmail(null)
              }}
              className="mt-6 w-full rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
            >
              Back to log in
            </button>
          </main>
          <Footer />
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto flex max-w-md flex-col px-6 pb-24 pt-8">
          <h1 className="font-display text-2xl font-semibold text-ink">
            {mode === 'login' ? 'Log in' : mode === 'register' ? 'Create your account' : 'Reset your password'}
          </h1>
          <p className="mt-2 text-sm text-ink-soft">
            {mode === 'forgot' ? (
              <button
                type="button"
                onClick={() => setMode('login')}
                className="font-medium text-ember hover:text-flame"
              >
                Back to log in
              </button>
            ) : (
              <>
                {mode === 'login' ? 'New here? ' : 'Already have an account? '}
                <button
                  type="button"
                  onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
                  className="font-medium text-ember hover:text-flame"
                >
                  {mode === 'login' ? 'Create an account' : 'Log in instead'}
                </button>
              </>
            )}
          </p>

          {sessionMessage && (
            <p className="mt-4 rounded-lg border border-line bg-mist px-3 py-2 text-sm text-ink-soft">
              {sessionMessage}
            </p>
          )}
          {searchParams.get('verified') === '1' && (
            <p className="mt-4 rounded-lg border border-line bg-mist px-3 py-2 text-sm text-ink-soft">
              Your email is verified — you can log in now.
            </p>
          )}
          {searchParams.get('verify_error') === '1' && (
            <p className="mt-4 rounded-lg border border-line bg-mist px-3 py-2 text-sm text-ink-soft">
              That verification link is invalid or has expired. Enter your email below and log in
              to request a new one.
            </p>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            {mode === 'register' && (
              <div>
                <label htmlFor="fullName" className="text-sm font-medium text-ink">
                  Full Name
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
            )}

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

            {mode !== 'forgot' && (
              <div>
                <div className="flex items-center justify-between">
                  <label htmlFor="password" className="text-sm font-medium text-ink">
                    Password
                  </label>
                  {mode === 'login' && (
                    <button
                      type="button"
                      onClick={() => setMode('forgot')}
                      className="text-xs font-medium text-ember hover:text-flame"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <div className="mt-2">
                  <PasswordInput
                    id="password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                </div>
                {mode === 'register' && (
                  <p className="mt-1 text-xs text-ink-soft">At least 8 characters.</p>
                )}
              </div>
            )}

            {error && (
              <div className="text-sm text-ember">
                <p>{error}</p>
                {errorCode === 'email_not_verified' && (
                  <button
                    type="button"
                    onClick={handleResend}
                    className="mt-1 font-medium underline decoration-line underline-offset-2 hover:text-flame"
                  >
                    Resend verification email
                  </button>
                )}
              </div>
            )}
            {resendStatus && resendStatus !== 'sending' && (
              <p className="text-sm text-ink-soft">{resendStatus}</p>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
            >
              {submitting
                ? 'Please wait…'
                : mode === 'login'
                  ? 'Log in'
                  : mode === 'register'
                    ? 'Create account'
                    : 'Send reset link'}
            </button>
          </form>
        </main>

        <Footer />
      </div>
    </div>
  )
}