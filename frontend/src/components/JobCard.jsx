import { useState } from 'react'
import ExternalRedirectModal from './ExternalRedirectModal'

const rejectReasons = [
  'Compensation mismatch',
  'Location / remote policy',
  'Role no longer open',
  'Not the right fit',
  'No response after applying',
]

// Once a user has confirmed the "you're leaving the site" notice, don't
// nag them again on every single Apply click.
const REDIRECT_NOTICE_KEY = 'sjh_seen_external_redirect_notice'

export default function JobCard({
  job,
  status,
  onStatusChange,
  shaded = false,
  canApply = false,
  onRequireSubscription = () => {},
}) {
  const [showRedirectModal, setShowRedirectModal] = useState(false)

  const formattedDate = new Date(job.datePosted).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })

  // Subscribed users see everything; everyone else only gets the title and
  // posted date, with the rest blurred out behind a subscribe hint.
  const isSubscribed = canApply

  function handleApplyClick(event) {
    if (typeof window !== 'undefined' && window.localStorage.getItem(REDIRECT_NOTICE_KEY)) {
      return // already confirmed before — let the link behave normally
    }
    event.preventDefault()
    setShowRedirectModal(true)
  }

  function confirmRedirect() {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(REDIRECT_NOTICE_KEY, '1')
    }
    setShowRedirectModal(false)
    window.open(job.applyUrl, '_blank', 'noopener,noreferrer')
  }

  return (
    <article
      className={`relative flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between ${
        shaded ? 'bg-mist' : 'bg-paper'
      }`}
    >
      {showRedirectModal && (
        <ExternalRedirectModal
          url={job.applyUrl}
          onConfirm={confirmRedirect}
          onCancel={() => setShowRedirectModal(false)}
        />
      )}

      <div className="flex-1">
        <h3 className="text-base font-semibold text-ink">{job.title}</h3>
        <p className="mt-1 text-sm text-ink">Posted on {formattedDate}</p>

        {isSubscribed ? (
          <>
            <p className="mt-1 text-sm text-ink">
              {job.company} &nbsp;&nbsp; {job.department} &nbsp;&nbsp; {job.location}
            </p>

            {job.otherJobsAtCompany > 0 && (
              <p className="mt-3 text-xs text-ink">
                There are {job.otherJobsAtCompany} jobs at this company.{' '}
                <button type="button" className="font-medium text-ember hover:text-flame">
                  See them all
                </button>
              </p>
            )}
          </>
        ) : (
          <>
            <p
              aria-hidden="true"
              className="mt-1 select-none whitespace-nowrap text-sm text-ink blur-[5px]"
            >
              {job.company || 'Company Name'} &nbsp;&nbsp; {job.department || 'Department'} &nbsp;&nbsp;{' '}
              {job.location || 'Location'}
            </p>
            <button
              type="button"
              onClick={onRequireSubscription}
              className="mt-2 text-xs font-medium text-ember hover:text-flame"
            >
              🔒 Subscribe to unlock company, department &amp; location
            </button>
          </>
        )}
      </div>

      <div className="flex flex-col items-start gap-2 sm:items-end">
        {!job.applyUrl ? (
          <button
            type="button"
            disabled
            title="No application link found for this listing yet"
            className="cursor-not-allowed rounded-md bg-moss/40 px-8 py-2 text-sm font-semibold text-white"
          >
            Apply
          </button>
        ) : canApply ? (
          <a
            href={job.applyUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleApplyClick}
            className="rounded-md bg-moss px-8 py-2 text-center text-sm font-semibold text-white hover:opacity-90"
          >
            Apply
          </a>
        ) : (
          // Not html-disabled on purpose: it needs to stay clickable so we
          // can prompt the subscribe modal instead of just looking inert.
          <button
            type="button"
            onClick={onRequireSubscription}
            title="Subscribe to apply"
            className="rounded-md bg-moss/40 px-8 py-2 text-sm font-semibold text-white blur-[1.5px]"
          >
            Apply
          </button>
        )}

        <p className="text-xs font-medium text-ink-soft">Did/Will You Apply?</p>

        <label className="flex items-center gap-1.5 text-sm text-ink">
          <input
            type="radio"
            name={`status-${job.id}`}
            checked={status.value === 'applied'}
            onChange={() => onStatusChange({ value: 'applied', reason: status.reason })}
          />
          Applied
        </label>
        <label className="flex items-center gap-1.5 text-sm text-ink">
          <input
            type="radio"
            name={`status-${job.id}`}
            checked={status.value === 'rejected'}
            onChange={() => onStatusChange({ value: 'rejected', reason: status.reason })}
          />
          Rejected
        </label>

        {status.value === 'rejected' && (
          <div className="w-full sm:w-44">
            <label className="text-xs text-ink-soft">Reason Rejected</label>
            <select
              value={status.reason}
              onChange={(event) => onStatusChange({ value: status.value, reason: event.target.value })}
              className="mt-1 w-full border border-line px-2 py-1.5 text-sm text-ink focus:border-ink-soft focus:outline-none"
            >
              <option value="">Select a reason…</option>
              {rejectReasons.map((reason) => (
                <option key={reason} value={reason}>
                  {reason}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </article>
  )
}