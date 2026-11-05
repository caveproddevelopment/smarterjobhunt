import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import SEO from '../components/SEO'
import BriefSharePanel from '../components/BriefSharePanel'
import {
  Avatar, BlogBody, BlogShell, RichBody, CommentIcon, HeartIcon, SubscribePrompt,
} from '../components/BlogParts'
import {
  addComment, banCommenter, deleteComment, deletePost, fetchBlogMe, fetchComments, fetchPost,
  formatDate, imageUrl, kickerLabel, postIdFromParam, readingMinutes, recordVisit, toggleLike,
} from '../lib/blogApi'
import { useAuth } from '../lib/auth'

export default function BlogPost() {
  const { slug } = useParams()
  const postId = postIdFromParam(slug)
  const navigate = useNavigate()
  const { user } = useAuth()
  const [me, setMe] = useState({ logged_in: false, can_write: false, can_engage: false, is_admin: false })
  const [post, setPost] = useState(null)
  const [comments, setComments] = useState([])
  const [notFound, setNotFound] = useState(false)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchBlogMe().then(setMe).catch(() => {})
  }, [user])

  useEffect(() => {
    if (!postId) {
      setNotFound(true)
      return
    }
    setNotFound(false)
    fetchPost(postId)
      .then((p) => {
        setPost(p)
        if (p.status === 'published') recordVisit(p.id)
        // keep the URL's slug in sync with the title
        if (`/blog/${slug}` !== p.path) navigate(p.path, { replace: true })
      })
      .catch(() => setNotFound(true))
    fetchComments(postId).then(setComments).catch(() => setComments([]))
  }, [postId, user]) // eslint-disable-line react-hooks/exhaustive-deps

  async function run(fn) {
    setError(null)
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const onLike = () =>
    run(async () => {
      const res = await toggleLike(post.id)
      setPost((p) => ({ ...p, liked_by_me: res.liked, like_count: res.like_count }))
    })

  const onComment = (e) => {
    e.preventDefault()
    if (!comment.trim()) return
    run(async () => {
      const c = await addComment(post.id, comment)
      setComments((prev) => [...prev, c])
      setPost((p) => ({ ...p, comment_count: p.comment_count + 1 }))
      setComment('')
    })
  }

  const onDeleteComment = (id) =>
    window.confirm('Delete this comment?') &&
    run(async () => {
      await deleteComment(id)
      setComments((prev) => prev.filter((c) => c.id !== id))
      setPost((p) => ({ ...p, comment_count: p.comment_count - 1 }))
    })

  const onBan = (c) => {
    const reason = window.prompt(
      `Ban ${c.author.name} from commenting? They can still read and like posts.\n\nReason (only admins see this):`,
      '',
    )
    if (reason === null) return
    const deleteAll = window.confirm(
      `Also delete ALL of ${c.author.name}'s comments on every post?\n\nOK = delete all their comments\nCancel = delete only this comment`,
    )
    run(async () => {
      await banCommenter(c.id, { reason, deleteAll })
      const fresh = await fetchComments(post.id)
      setComments(fresh)
      setPost((p) => ({ ...p, comment_count: fresh.length }))
    })
  }

  const onDeletePost = () =>
    window.confirm('Delete this post permanently? This cannot be undone.') &&
    run(async () => {
      await deletePost(post.id)
      navigate('/blog')
    })


  if (notFound) {
    return (
      <BlogShell>
        <div className="mx-auto max-w-2xl py-20 text-center">
          <h1 className="font-display text-2xl font-semibold text-ink">Post not found</h1>
          <p className="mt-2 text-ink-soft">It may have been removed.</p>
          <Link to="/blog" className="mt-6 inline-block font-semibold text-ember hover:underline">Back to The Brief</Link>
        </div>
      </BlogShell>
    )
  }
  if (!post) {
    return <BlogShell><p className="py-20 text-center text-sm text-ink-soft">Loading...</p></BlogShell>
  }

  const cover = imageUrl(post.cover_url)
  const isPublished = post.status === 'published'

  return (
    <BlogShell>
      <SEO title={`${post.title} | The JobBeggar Brief`} description={post.subtitle || post.excerpt} path={post.path} image={cover || undefined} />
      <article className="mx-auto max-w-3xl py-6">
        <Link to="/blog" className="text-sm font-semibold text-ink-soft hover:text-ink">&larr; The JobBeggar Brief</Link>

        <p className="mt-6 font-mono text-xs font-semibold tracking-[0.14em] text-ember">
          {post.category ? (
            <Link to={`/blog?category=${encodeURIComponent(post.category)}`} className="hover:underline">
              {kickerLabel(post)}
            </Link>
          ) : kickerLabel(post)}
        </p>
        <h1 className="mt-3 font-display text-3xl font-semibold leading-tight text-ink md:text-5xl">{post.title}</h1>
        {post.subtitle && (
          <p className="mt-3 text-xl leading-snug text-ink-soft md:text-2xl">{post.subtitle}</p>
        )}
        <div className="mt-5 flex flex-wrap items-center gap-3 text-sm text-ink-soft">
          <Avatar initials={post.author.initials} />
          <span className="font-semibold text-ink">{post.author.name}</span>
          <span>·</span>
          <span>{formatDate(post.published_at || post.updated_at)}</span>
          <span>·</span>
          <span>{readingMinutes(post.body)} min read</span>
        </div>

        {cover && <img src={cover} alt="" className="mt-8 w-full rounded-2xl object-cover" />}

        <div className="mt-8">
          {post.body_html ? <RichBody html={post.body_html} /> : <BlogBody text={post.body} />}
        </div>

        {me.can_write && (
          <div className="mt-10 flex flex-wrap gap-3 border-t border-line pt-6">
            <Link to={`/blog/${post.id}/edit`}
              className="rounded-full border border-line px-5 py-2 text-sm font-semibold text-ink hover:bg-mist">Edit</Link>
            <button type="button" disabled={busy} onClick={onDeletePost}
              className="rounded-full border border-ember/40 px-5 py-2 text-sm font-semibold text-ember hover:bg-ember/5 disabled:opacity-50">
              Delete
            </button>
          </div>
        )}

        {me.is_admin && post.status === 'published' && <BriefSharePanel post={post} />}

        {error && <p className="mt-6 rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}

        {isPublished && (
          <section className="mt-10 border-t border-line pt-8">
            <div className="flex items-center gap-4">
              <button type="button" onClick={onLike} disabled={busy || !me.can_engage}
                title={me.can_engage ? (post.liked_by_me ? 'Unlike' : 'Like') : 'Subscribers can like posts'}
                className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed ${
                  post.liked_by_me ? 'border-ember bg-ember/10 text-ember' : 'border-line text-ink hover:bg-mist'
                }`}>
                <HeartIcon filled={post.liked_by_me} /> {post.like_count}
              </button>
              <span className="flex items-center gap-2 text-sm text-ink-soft"><CommentIcon /> {post.comment_count} {post.comment_count === 1 ? 'comment' : 'comments'}</span>
            </div>

            <h2 className="mt-8 font-display text-xl font-semibold text-ink">Comments</h2>
            <div className="mt-4 space-y-5">
              {comments.length === 0 && <p className="text-sm text-ink-soft">No comments yet.</p>}
              {comments.map((c) => (
                <div key={c.id} className="flex gap-3">
                  <Avatar initials={c.author.initials} size="h-8 w-8 text-[11px]" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-semibold text-ink">{c.author.name}</span>
                      <span className="text-xs text-ink-soft">{formatDate(c.created_at)}</span>
                      <span className="ml-auto flex gap-3">
                        {c.can_ban && (
                          <button type="button" onClick={() => onBan(c)}
                            className="text-xs font-semibold text-ember hover:underline">Ban user</button>
                        )}
                        {c.can_delete && (
                          <button type="button" onClick={() => onDeleteComment(c.id)}
                            className="text-xs font-semibold text-ink-soft hover:text-ember">Delete</button>
                        )}
                      </span>
                    </div>
                    <p className="mt-1 whitespace-pre-line break-words text-sm leading-relaxed text-ink">{c.body}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-8">
              {me.comment_banned ? (
                <p className="rounded-2xl border border-line bg-mist p-5 text-sm text-ink-soft">
                  You've been blocked from commenting.
                </p>
              ) : me.can_engage ? (
                <form onSubmit={onComment} className="space-y-3">
                  <textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} rows={3}
                    placeholder="Add a comment..."
                    className="w-full rounded-xl border border-line bg-white p-3 text-sm text-ink outline-none focus:border-ember" />
                  <button type="submit" disabled={busy || !comment.trim()}
                    className="flame-gradient rounded-full px-5 py-2 text-sm font-semibold text-white disabled:opacity-50">
                    Post comment
                  </button>
                </form>
              ) : (
                <SubscribePrompt loggedIn={me.logged_in} action="comment and like posts" />
              )}
            </div>
          </section>
        )}
      </article>
    </BlogShell>
  )
}
