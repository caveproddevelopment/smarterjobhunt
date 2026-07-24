const rejectReasons = [
  'Compensation mismatch',
  'Location / remote policy',
  'Role no longer open',
  'Not the right fit',
  'No response after applying',
]

export default function JobCard({ job, status, onStatusChange, shaded = false }) {
  const formattedDate = new Date(job.datePosted).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })

  return (
    <article
      className={`flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between ${
        shaded ? 'bg-mist' : 'bg-paper'
      }`}
    >
      <div className="flex-1">
        <h3 className="text-base font-semibold text-ink">{job.title}</h3>
        <p className="mt-1 text-sm text-ink">
          {job.company} &nbsp;&nbsp; {job.department} &nbsp;&nbsp; {job.location}
        </p>
        <p className="mt-1 text-sm text-ink">
          {formattedDate} &nbsp;&nbsp; {job.match}% match &nbsp;&nbsp; {job.funding}
        </p>

        {job.otherJobsAtCompany > 0 && (
          <p className="mt-3 text-xs text-ink">
            There are {job.otherJobsAtCompany} jobs at this company.{' '}
            <button type="button" className="font-medium text-ember hover:text-flame">
              See them all
            </button>
          </p>
        )}
      </div>

      <div className="flex flex-col items-start gap-2 sm:items-end">
        <button type="button" className="rounded-md bg-moss px-8 py-2 text-sm font-semibold text-white">
          Apply
        </button>

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