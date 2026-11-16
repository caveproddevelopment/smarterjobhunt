import { useNavigate } from 'react-router-dom'

// Shown when a signed-out visitor tries to apply. JobBeggar is free, so
// this just sends them to log in / sign up.
export default function SubscribeModal({ onClose }) {
  const navigate = useNavigate()

  function handleLogin() {
    onClose()
    navigate('/login')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-md border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">Log in to apply</h2>
        <p className="mt-1 text-sm text-ink-soft">
          JobBeggar is free. Create an account or log in to see full job details and apply.
        </p>

        <button
          type="button"
          onClick={handleLogin}
          className="mt-5 w-full rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
        >
          Log in or sign up — free
        </button>

        <button
          type="button"
          onClick={onClose}
          className="mt-3 w-full rounded-full border border-line py-2.5 text-sm font-medium text-ink hover:bg-mist"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
