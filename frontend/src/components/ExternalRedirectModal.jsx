function getHostname(url) {
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

export default function ExternalRedirectModal({ url, onConfirm, onCancel }) {
  const hostname = getHostname(url)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <div className="w-full max-w-sm border border-line bg-paper p-6 shadow-xl">
        <h2 className="font-display text-lg font-semibold text-ink">You're leaving SmarterJobHunt</h2>
        <p className="mt-2 text-sm text-ink-soft">
          You're about to be redirected to an external site
          {hostname ? (
            <>
              {' '}
              (<span className="font-medium text-ink">{hostname}</span>)
            </>
          ) : null}{' '}
          to complete your application. We aren't responsible for its content.
        </p>

        <div className="mt-5 flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 rounded-full border border-line py-2.5 text-sm font-medium text-ink transition-colors hover:bg-mist"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="flex-1 rounded-full flame-gradient py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  )
}
