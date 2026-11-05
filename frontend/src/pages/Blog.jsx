import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogShell, PostCard, SubscribePrompt } from '../components/BlogParts'
import { fetchBlogMe, fetchPosts } from '../lib/blogApi'
import { useAuth } from '../lib/auth'

export default function Blog() {
  const { user } = useAuth()
  const [me, setMe] = useState({ logged_in: false, can_write: false, can_engage: false, is_admin: false })
  const [posts, setPosts] = useState([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchBlogMe().then(setMe).catch(() => {})
  }, [user])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchPosts(page)
      .then((data) => {
        if (cancelled) return
        setPosts((prev) => (page === 1 ? data.posts : [...prev, ...data.posts]))
        setHasMore(data.has_more)
      })
      .catch((err) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [page, user])

  return (
    <BlogShell>
      <SEO
        title="The JobBeggar Brief"
        description="Hiring signals pulled straight from company career pages."
        path="/blog"
      />
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-col gap-4 py-8 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-ember">The Brief</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
              The JobBeggar Brief
            </h1>
            <p className="mt-2 max-w-xl text-ink-soft">
              Hiring signals pulled straight from company career pages.
            </p>
          </div>
          {me.is_admin && (
            <div className="flex flex-wrap gap-3 self-start sm:self-auto">
              <Link to="/blog/moderation"
                className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold text-ink hover:bg-mist">
                Banned commenters
              </Link>
              {me.can_write && (
                <Link to="/blog/new"
                  className="flame-gradient rounded-full px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]">
                  Write a post
                </Link>
              )}
            </div>
          )}
        </div>

        {!me.can_engage && (
          <div className="mb-8">
            <SubscribePrompt loggedIn={me.logged_in} />
          </div>
        )}

        {error && <p className="rounded-xl bg-ember/10 p-4 text-sm text-ember">{error}</p>}

        {!loading && !error && posts.length === 0 && (
          <div className="rounded-2xl border border-dashed border-line p-10 text-center text-ink-soft">
            No posts yet. Check back soon!
          </div>
        )}

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {posts.map((post) => (
            <PostCard key={post.id} post={post} />
          ))}
        </div>

        {loading && <p className="py-8 text-center text-sm text-ink-soft">Loading...</p>}

        {hasMore && !loading && (
          <div className="mt-10 text-center">
            <button type="button" onClick={() => setPage((p) => p + 1)}
              className="rounded-full border border-line px-6 py-2.5 text-sm font-semibold text-ink hover:bg-mist">
              Load more
            </button>
          </div>
        )}
      </div>
    </BlogShell>
  )
}
