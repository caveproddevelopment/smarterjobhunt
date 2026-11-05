import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogBody, BlogShell, StatusBadge } from '../components/BlogParts'
import {
  approvePost, deletePost, fetchAdminPosts, fetchBlogMe, formatDate, imageUrl, rejectPost,
} from '../lib/blogApi'
import { useAuth } from '../lib/auth'

const TABS = [['pending', 'Waiting'], ['published', 'Published'], ['rejected', 'Rejected']]

export default function BlogAdmin() {
  const { user, loading: authLoading } = useAuth()
  const [me, setMe] = useState(null)
  const [status, setStatus] = useState('pending')
  const [posts, setPosts] = useState([])
  const [open, setOpen] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (authLoading) return
    fetchBlogMe().then(setMe).catch(() => setMe({ is_admin: false }))
  }, [user, authLoading])

  useEffect(() => {
    if (!me?.is_admin) return
    setError(null)
    fetchAdminPosts(status).then(setPosts).catch((err) => setError(err.message))
  }, [me, status])

  async function act(id, fn) {
    setBusyId(id)
    setError(null)
    try {
      await fn()
      setPosts((prev) => prev.filter((p) => p.id !== id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  const onReject = (post) => {
    const reason = window.prompt(`Why is "${post.title}" not approved? (the author will see this)`, '')
    if (reason !== null) act(post.id, () => rejectPost(post.id, reason))
  }
  const onDelete = (post) =>
    window.confirm(`Delete "${post.title}" permanently?`) && act(post.id, () => deletePost(post.id))

  if (!me) return <BlogShell><p className="py-20 text-center text-sm text-ink-soft">Loading...</p></BlogShell>
  if (!me.is_admin) {
    return (
      <BlogShell>
        <div className="mx-auto max-w-2xl py-20 text-center">
          <h1 className="font-display text-2xl font-semibold text-ink">Admins only</h1>
          <Link to="/blog" className="mt-6 inline-block font-semibold text-ember hover:underline">Back to the blog</Link>
        </div>
      </BlogShell>
    )
  }

  return (
    <BlogShell>
      <SEO title="Review blog posts | JobBeggar" path="/blog/admin" />
      <div className="mx-auto max-w-4xl py-6">
        <Link to="/blog" className="text-sm font-semibold text-ink-soft hover:text-ink">&larr; Blog</Link>
        <h1 className="mt-4 font-display text-3xl font-semibold text-ink">Review blog posts</h1>

        <div className="mt-6 flex gap-2 border-b border-line">
          {TABS.map(([key, label]) => (
            <button key={key} type="button" onClick={() => setStatus(key)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold ${
                status === key ? 'border-ember text-ink' : 'border-transparent text-ink-soft hover:text-ink'
              }`}>{label}</button>
          ))}
        </div>

        {error && <p className="mt-4 rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}
        {posts.length === 0 && <p className="py-12 text-center text-ink-soft">Nothing here.</p>}

        <div className="mt-6 space-y-4">
          {posts.map((post) => (
            <div key={post.id} className="rounded-2xl border border-line bg-white p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <StatusBadge status={post.status} />
                  <h2 className="mt-2 font-display text-lg font-semibold text-ink">{post.title}</h2>
                  <p className="mt-1 text-xs text-ink-soft">
                    {post.author.name} · updated {formatDate(post.updated_at)}
                    {post.reject_reason ? ` · Reason: ${post.reject_reason}` : ''}
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  {post.status !== 'published' && (
                    <button type="button" disabled={busyId === post.id} onClick={() => act(post.id, () => approvePost(post.id))}
                      className="rounded-full bg-moss px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Approve</button>
                  )}
                  {post.status !== 'rejected' && (
                    <button type="button" disabled={busyId === post.id} onClick={() => onReject(post)}
                      className="rounded-full border border-line px-4 py-2 text-sm font-semibold text-ink disabled:opacity-50">
                      {post.status === 'published' ? 'Unpublish' : 'Reject'}
                    </button>
                  )}
                  <button type="button" disabled={busyId === post.id} onClick={() => onDelete(post)}
                    className="rounded-full border border-ember/40 px-4 py-2 text-sm font-semibold text-ember disabled:opacity-50">Delete</button>
                </div>
              </div>
              <button type="button" onClick={() => setOpen(open === post.id ? null : post.id)}
                className="mt-3 text-sm font-semibold text-ember hover:underline">
                {open === post.id ? 'Hide post' : 'Read post'}
              </button>
              {open === post.id && (
                <div className="mt-4 border-t border-line pt-4">
                  {post.cover_url && <img src={imageUrl(post.cover_url)} alt="" className="mb-4 w-full rounded-xl" />}
                  <BlogBody text={post.body} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </BlogShell>
  )
}
