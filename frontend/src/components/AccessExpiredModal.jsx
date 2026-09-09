import { Link } from 'react-router-dom'

// Shown instead of running the search whenever a signed-in user whose
// 24-hour trial has ended (and who isn't Pro) tries to search by job
// title -- see `canApply` in JobListings.jsx (plan === 'pro' || trial_active).
// Distinct from SubscribeModal (which gates the per-job "Apply" action);
// this one gates the search itself.
export default function AccessExpiredModal({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-md border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">Free Access Expired</h2>
        <p className="mt-1 text-sm text-ink-soft">
          Your 24-hour free trial has ended. Subscribe to keep searching job titles.
        </p>

        <Link
          to="/pricing"
          onClick={onClose}
          className="mt-5 block w-full rounded-full flame-gradient py-2.5 text-center text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
        >
          Restore Full Access Here
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
