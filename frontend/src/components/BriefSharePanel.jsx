// Admin-only "Share & track" panel on an article: ready-made tracked links for
// each channel, and how many visits / sign-ups each channel brought in.
import { useEffect, useState } from 'react'
import { fetchPostStats } from '../lib/blogApi'

const SHARE_CHANNELS = [
  ['linkedin', 'LinkedIn', 'social'],
  ['x', 'X (Twitter)', 'social'],
  ['facebook', 'Facebook', 'social'],
  ['instagram', 'Instagram', 'social'],
  ['whatsapp', 'WhatsApp', 'messaging'],
  ['reddit', 'Reddit', 'social'],
  ['email', 'Email', 'email'],
  ['newsletter', 'Newsletter', 'email'],
]

// utm_content "brief-<post id>" ties sign-ups to this exact article
// (frontend/src/lib/utm.js saves it on the visitor's first tagged visit).
function trackedLink(post, source, medium) {
  const url = new URL(post.path, window.location.origin)
  url.search = new URLSearchParams({
    utm_source: source,
    utm_medium: medium,
    utm_campaign: 'the_brief',
    utm_content: `brief-${post.id}`,
  }).toString()
  return url.toString()
}

function CopyRow({ label, link }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(link)
    } catch {
      window.prompt('Copy this link:', link)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-sm font-semibold text-ink">{label}</span>
      <input readOnly value={link} onFocus={(e) => e.target.select()} aria-label={`${label} link`}
        className="min-w-0 flex-1 truncate rounded-lg border border-line bg-mist px-3 py-1.5 font-mono text-xs text-ink-soft" />
      <button type="button" onClick={copy}
        className="w-20 shrink-0 rounded-full border border-line px-3 py-1.5 text-xs font-semibold text-ink hover:bg-mist">
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

export default function BriefSharePanel({ post }) {
  const [open, setOpen] = useState(false)
  const [stats, setStats] = useState(null)
  const [custom, setCustom] = useState('')
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    fetchPostStats(post.id).then(setStats).catch((err) => setError(err.message))
  }, [open, post.id])

  const customSource = custom.toLowerCase().replace(/[^a-z0-9_-]+/g, '').slice(0, 30)

  return (
    <section className="mt-10 rounded-2xl border border-line bg-white">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span>
          <span className="font-display text-lg font-semibold text-ink">Share &amp; track</span>
          <span className="block text-xs text-ink-soft">Admins only · tracked links and where readers came from</span>
        </span>
        <span className="text-sm font-semibold text-ember">{open ? 'Hide' : 'Open'}</span>
      </button>
      {open && (
        <div className="space-y-6 border-t border-line px-5 py-5">
          <div className="space-y-2">
            <p className="text-xs text-ink-soft">
              Post the link for the channel you&rsquo;re sharing on. Visits and sign-ups from it are credited to
              this article (<span className="font-mono">brief-{post.id}</span>).
            </p>
            {SHARE_CHANNELS.map(([src, label, medium]) => (
              <CopyRow key={src} label={label} link={trackedLink(post, src, medium)} />
            ))}
            <div className="flex items-center gap-2 pt-2">
              <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Other channel, e.g. podcast"
                aria-label="Custom channel name"
                className="w-28 shrink-0 rounded-lg border border-line px-2 py-1.5 text-xs text-ink outline-none focus:border-ember" />
              {customSource ? (
                <div className="min-w-0 flex-1"><CopyRow label="" link={trackedLink(post, customSource, 'referral')} /></div>
              ) : (
                <span className="text-xs text-ink-soft">Type a name to make a link for any other place.</span>
              )}
            </div>
          </div>

          {error && <p className="rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}
          {stats && (
            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <h3 className="text-sm font-semibold text-ink">Visits by source</h3>
                <p className="text-xs text-ink-soft">{stats.total_visits.toLocaleString()} total (one per reader per session)</p>
                <table className="mt-2 w-full text-sm">
                  <thead><tr className="text-left text-xs text-ink-soft"><th className="py-1 font-medium">Source</th>
                    <th className="py-1 text-right font-medium">7 days</th><th className="py-1 text-right font-medium">All time</th></tr></thead>
                  <tbody>
                    {stats.visits_by_source.length === 0 && (
                      <tr><td colSpan={3} className="py-2 text-ink-soft">No visits yet.</td></tr>
                    )}
                    {stats.visits_by_source.map((v) => (
                      <tr key={v.source} className="border-t border-line">
                        <td className="py-1.5 text-ink">{v.source}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink-soft">{v.last_7_days.toLocaleString()}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink">{v.visits.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="text-sm font-semibold text-ink">Sign-ups from this article</h3>
                <p className="text-xs text-ink-soft">
                  {stats.total_signups} sign-up{stats.total_signups === 1 ? '' : 's'} · {stats.total_subscribers} now
                  subscribed
                </p>
                <table className="mt-2 w-full text-sm">
                  <thead><tr className="text-left text-xs text-ink-soft"><th className="py-1 font-medium">Source</th>
                    <th className="py-1 text-right font-medium">Sign-ups</th><th className="py-1 text-right font-medium">Subscribed</th></tr></thead>
                  <tbody>
                    {stats.signups_by_source.length === 0 && (
                      <tr><td colSpan={3} className="py-2 text-ink-soft">None yet.</td></tr>
                    )}
                    {stats.signups_by_source.map((s) => (
                      <tr key={s.source} className="border-t border-line">
                        <td className="py-1.5 text-ink">{s.source}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink">{s.signups}</td>
                        <td className="py-1.5 text-right tabular-nums text-ink">{s.subscribers}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-ink-soft">
                  Counts people whose first tracked link was this article, even if they signed up later.
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
