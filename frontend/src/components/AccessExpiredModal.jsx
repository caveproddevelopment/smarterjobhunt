import { Link } from 'react-router-dom'

// Shown when a user tries to access job discovery without the weekly
// subscription or its seven-day trial.
export default function AccessExpiredModal({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-md border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">Subscription required</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Start the weekly plan to search jobs and view full listing details. Your first week is free.
        </p>

        <Link
          to="/pricing"
          onClick={onClose}
          className="mt-5 block w-full rounded-full flame-gradient py-2.5 text-center text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
        >
          Start your free week
        </Link>

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