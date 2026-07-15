import PillRadioGroup from './PillRadioGroup'

const rejectReasons = [
  'Compensation mismatch',
  'Location / remote policy',
  'Role no longer open',
  'Not the right fit',
  'No response after applying',
]

export default function JobCard({ job, status, onStatusChange }) {
  const formattedDate = new Date(job.datePosted).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })

  return (
    <article className="flex flex-col gap-4 rounded-lg border border-line bg-white p-5 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex-1">
        <h3 className="font-display text-base font-semibold text-ink">{job.title}</h3>
        <p className="mt-1 text-sm text-ink-soft">
          {job.company} · {job.department} · {job.location}
        </p>
        <p className="mt-1 text-sm text-ink-soft">
          {formattedDate} · {job.match}% match · {job.funding}
        </p>

        {job.otherJobsAtCompany > 0 && (
          <p className="mt-4 text-xs text-ink-soft">
            There are {job.otherJobsAtCompany} jobs at this company.{' '}
            <button type="button" className="font-medium text-ember hover:text-flame">
              See them all
            </button>
          </p>
        )}
      </div>

      <div className="flex flex-col items-start gap-3 sm:items-end">
        <button
          type="button"
          className="rounded-md bg-moss px-8 py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.03]"
        >
          Apply
        </button>

        <PillRadioGroup
          name={`Status for ${job.title}`}
          value={status.value}
          onChange={(value) => onStatusChange({ value, reason: status.reason })}
          options={[
            { value: 'applied', label: 'Applied' },
            { value: 'rejected', label: 'Rejected' },
          ]}
        />

        {status.value === 'rejected' && (
          <div className="w-full sm:w-48">
            <label className="text-xs font-medium text-ink-soft">Reason rejected</label>
            <select
              value={status.reason}
              onChange={(event) =>
                onStatusChange({ value: status.value, reason: event.target.value })
              }
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
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