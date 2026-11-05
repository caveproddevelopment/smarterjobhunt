import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogShell, PostCard, SubscribePrompt } from '../components/BlogParts'
import { fetchBlogMe, fetchMyPosts, fetchPosts } from '../lib/blogApi'
import { useAuth } from '../lib/auth'

export default function Blog() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'mine' ? 'mine' : 'all'
  const [me, setMe] = useState({ logged_in: false, can_write: false, is_admin: false })
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
    const load = tab === 'mine' ? fetchMyPosts : fetchPosts
    load(page)
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
  }, [tab, page, user])

  function switchTab(next) {
    setPage(1)
    setPosts([])
    setParams(next === 'mine' ? { tab: 'mine' } : {})
  }

  return (
    <BlogShell>
      <SEO
        title="JobBeggar Blog"
        description="Job-hunting stories, tips and lessons written by the JobBeggar community."
        path="/blog"
      />
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-col gap-4 py-8 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wide text-ember">Blog</p>
            <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
              Stories from the job hunt
            </h1>
            <p className="mt-2 max-w-xl text-ink-soft">
              Tips, wins and lessons written by JobBeggar subscribers.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            {me.is_admin && (
              <Link to="/blog/admin"
                className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold text-ink hover:bg-mist">
                Review posts
              </Link>
            )}
            {me.can_write && (
              <Link to="/blog/new"
                className="flame-gradient rounded-full px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]">
                Write a post
              </Link>
            )}
          </div>
        </div>

        {me.logged_in && (
          <div className="mb-6 flex gap-2 border-b border-line">
            {[['all', 'All posts'], ['mine', 'My posts']].map(([key, label]) => (
              <button key={key} type="button" onClick={() => switchTab(key)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold ${
                  tab === key ? 'border-ember text-ink' : 'border-transparent text-ink-soft hover:text-ink'
                }`}>
                {label}
              </button>
            ))}
          </div>
        )}

        {!me.can_write && (
          <div className="mb-8">
            <SubscribePrompt loggedIn={me.logged_in} />
          </div>
        )}

        {error && <p className="rounded-xl bg-ember/10 p-4 text-sm text-ember">{error}</p>}

        {!loading && !error && posts.length === 0 && (
          <div className="rounded-2xl border border-dashed border-line p-10 text-center text-ink-soft">
            {tab === 'mine'
              ? "You haven't written any posts yet."
              : 'No posts yet. Check back soon!'}
          </div>
        )}

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {posts.map((post) => (
            <PostCard key={post.id} post={post} showStatus={tab === 'mine'} />
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
