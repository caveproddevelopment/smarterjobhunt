import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'

export default function SubscribeModal({ onClose }) {
  const { user, startCheckout } = useAuth()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubscribe(interval) {
    setError(null)
    setLoading(true)
    try {
      await startCheckout(interval) // redirects to Stripe on success
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  function handleLogin() {
    onClose()
    navigate('/login')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-md border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">Subscribe to apply</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Applying to roles is a Pro feature. Pick a plan to unlock it.
        </p>

        {error && <p className="mt-3 text-sm text-ember">{error}</p>}

        {user ? (
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => handleSubscribe('week')}
              disabled={loading}
              className="rounded-lg border border-line px-4 py-3 text-left transition-colors hover:bg-mist disabled:opacity-60"
            >
              <p className="text-sm font-semibold text-ink">Weekly</p>
              <p className="text-xs text-ink-soft">Billed every week, cancel anytime.</p>
            </button>
            <button
              type="button"
              onClick={() => handleSubscribe('month')}
              disabled={loading}
              className="rounded-lg border border-line px-4 py-3 text-left transition-colors hover:bg-mist disabled:opacity-60"
            >
              <p className="text-sm font-semibold text-ink">Monthly</p>
              <p className="text-xs text-ink-soft">Billed every month, cancel anytime.</p>
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={handleLogin}
            className="mt-5 w-full rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
          >
            Log in to subscribe
          </button>
        )}

        <button
          type="button"
          onClick={onClose}
          disabled={loading}
          className="mt-3 w-full rounded-full border border-line py-2.5 text-sm font-medium text-ink hover:bg-mist disabled:opacity-60"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
