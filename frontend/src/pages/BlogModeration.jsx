import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogShell } from '../components/BlogParts'
import { fetchBans, fetchBlogMe, formatDate, unbanUser } from '../lib/blogApi'
import { useAuth } from '../lib/auth'

// Admin list of users banned from commenting on The JobBeggar Brief.
// Bans are made from a comment's "Ban user" button on the post page.
export default function BlogModeration() {
  const { user, loading: authLoading } = useAuth()
  const [me, setMe] = useState(null)
  const [bans, setBans] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (authLoading) return
    fetchBlogMe().then(setMe).catch(() => setMe({ is_admin: false }))
  }, [user, authLoading])

  useEffect(() => {
    if (me?.is_admin) fetchBans().then(setBans).catch((err) => setError(err.message))
  }, [me])

  async function onUnban(ban) {
    if (!window.confirm(`Let ${ban.name} comment again?`)) return
    try {
      await unbanUser(ban.user_id)
      setBans((prev) => prev.filter((b) => b.user_id !== ban.user_id))
    } catch (err) {
      setError(err.message)
    }
  }

  if (!me) return <BlogShell><p className="py-20 text-center text-sm text-ink-soft">Loading...</p></BlogShell>
  if (!me.is_admin) {
    return (
      <BlogShell>
        <div className="mx-auto max-w-2xl py-20 text-center">
          <h1 className="font-display text-2xl font-semibold text-ink">Admins only</h1>
          <Link to="/blog" className="mt-6 inline-block font-semibold text-ember hover:underline">Back to The Brief</Link>
        </div>
      </BlogShell>
    )
  }

  return (
    <BlogShell>
      <SEO title="Banned commenters | The JobBeggar Brief" path="/blog/moderation" />
      <div className="mx-auto max-w-3xl py-6">
        <Link to="/blog" className="text-sm font-semibold text-ink-soft hover:text-ink">&larr; The JobBeggar Brief</Link>
        <h1 className="mt-4 font-display text-3xl font-semibold text-ink">Banned commenters</h1>
        <p className="mt-2 text-sm text-ink-soft">
          These people can still read and like posts but can't comment. To ban someone, click
          &ldquo;Ban user&rdquo; next to one of their comments.
        </p>
        {error && <p className="mt-4 rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}
        {bans.length === 0 ? (
          <p className="mt-10 rounded-2xl border border-dashed border-line p-10 text-center text-ink-soft">
            Nobody is banned.
          </p>
        ) : (
          <div className="mt-6 divide-y divide-line rounded-2xl border border-line bg-white">
            {bans.map((ban) => (
              <div key={ban.user_id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{ban.name}</p>
                  <p className="truncate text-xs text-ink-soft">{ban.email} · banned {formatDate(ban.created_at)}</p>
                  {ban.reason && <p className="mt-1 text-sm text-ink-soft">Reason: {ban.reason}</p>}
                </div>
                <button type="button" onClick={() => onUnban(ban)}
                  className="self-start rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink hover:bg-mist sm:self-auto">
                  Unban
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </BlogShell>
  )
}
