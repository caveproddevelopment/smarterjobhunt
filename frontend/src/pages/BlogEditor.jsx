import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogBody, BlogShell, SubscribePrompt } from '../components/BlogParts'
import {
  createPost, fetchBlogMe, fetchPost, imageUrl, postIdFromParam, updatePost, uploadImage,
} from '../lib/blogApi'
import { useAuth } from '../lib/auth'

const TITLE_MAX = 150
const BODY_MIN = 50
const BODY_MAX = 20000
const IMAGE_MAX = 3 * 1024 * 1024

export default function BlogEditor() {
  const { id } = useParams()
  const postId = postIdFromParam(id)
  const editing = Boolean(id)
  const navigate = useNavigate()
  const { user, loading: authLoading } = useAuth()
  const fileInput = useRef(null)

  const [me, setMe] = useState(null)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [cover, setCover] = useState(null) // { id, url }
  const [preview, setPreview] = useState(false)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [loadingPost, setLoadingPost] = useState(editing)

  useEffect(() => {
    if (authLoading) return
    fetchBlogMe().then(setMe).catch(() => setMe({ logged_in: false, can_write: false }))
  }, [user, authLoading])

  useEffect(() => {
    if (!editing) return
    fetchPost(postId)
      .then((p) => {
        if (!p.is_mine) throw new Error("You can only edit your own posts.")
        setTitle(p.title)
        setBody(p.body)
        setCover(p.cover_image_id ? { id: p.cover_image_id, url: p.cover_url } : null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingPost(false))
  }, [editing, postId, user])

  async function onPickImage(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > IMAGE_MAX) {
      setError('Image must be 3 MB or smaller.')
      return
    }
    setError(null)
    setUploading(true)
    try {
      setCover(await uploadImage(file))
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  async function onSubmit(e) {
    e.preventDefault()
    setError(null)
    if (title.trim().length < 5) return setError('Title must be at least 5 characters.')
    if (body.trim().length < BODY_MIN) return setError(`Post must be at least ${BODY_MIN} characters.`)
    setBusy(true)
    try {
      const payload = { title, body, cover_image_id: cover?.id || null }
      const saved = editing ? await updatePost(postId, payload) : await createPost(payload)
      navigate(saved.path)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  if (!me || loadingPost) {
    return <BlogShell><p className="py-20 text-center text-sm text-ink-soft">Loading...</p></BlogShell>
  }
  if (!me.can_write) {
    return (
      <BlogShell>
        <div className="mx-auto max-w-2xl py-16">
          <h1 className="mb-6 font-display text-3xl font-semibold text-ink">Write a post</h1>
          <SubscribePrompt loggedIn={me.logged_in} action="write blog posts" />
        </div>
      </BlogShell>
    )
  }

  return (
    <BlogShell>
      <SEO title={editing ? 'Edit post | JobBeggar Blog' : 'Write a post | JobBeggar Blog'} path="/blog/new" />
      <form onSubmit={onSubmit} className="mx-auto max-w-3xl py-6">
        <Link to="/blog" className="text-sm font-semibold text-ink-soft hover:text-ink">&larr; All posts</Link>
        <h1 className="mt-4 font-display text-3xl font-semibold text-ink">{editing ? 'Edit post' : 'Write a post'}</h1>
        <p className="mt-2 text-sm text-ink-soft">
          Posts are reviewed by the JobBeggar team before they appear on the blog
          {editing ? ', and edits go back to review too' : ''}.
        </p>

        <label className="mt-8 block text-sm font-semibold text-ink" htmlFor="blog-title">Title</label>
        <input id="blog-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={TITLE_MAX}
          placeholder="How I landed interviews in 3 weeks"
          className="mt-2 w-full rounded-xl border border-line bg-white px-4 py-3 font-display text-xl text-ink outline-none focus:border-ember" />

        <div className="mt-6">
          <span className="block text-sm font-semibold text-ink">Cover image (optional)</span>
          {cover ? (
            <div className="mt-2">
              <img src={imageUrl(cover.url)} alt="" className="aspect-[16/9] w-full rounded-xl object-cover" />
              <div className="mt-2 flex gap-4 text-sm">
                <button type="button" onClick={() => fileInput.current?.click()} className="font-semibold text-ink hover:text-ember">Change</button>
                <button type="button" onClick={() => setCover(null)} className="font-semibold text-ink-soft hover:text-ember">Remove</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => fileInput.current?.click()} disabled={uploading}
              className="mt-2 flex w-full flex-col items-center justify-center rounded-xl border border-dashed border-line bg-white px-4 py-8 text-sm text-ink-soft hover:border-ember disabled:opacity-60">
              {uploading ? 'Uploading...' : 'Click to add a cover image'}
              <span className="mt-1 text-xs">JPG, PNG, WebP or GIF, up to 3 MB</span>
            </button>
          )}
          <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,image/gif" className="hidden" onChange={onPickImage} />
        </div>

        <div className="mt-6 flex items-center justify-between">
          <label className="text-sm font-semibold text-ink" htmlFor="blog-body">Post</label>
          <div className="flex rounded-full border border-line p-0.5 text-xs font-semibold">
            {[[false, 'Write'], [true, 'Preview']].map(([value, label]) => (
              <button key={label} type="button" onClick={() => setPreview(value)}
                className={`rounded-full px-3 py-1 ${preview === value ? 'bg-ink text-white' : 'text-ink-soft'}`}>{label}</button>
            ))}
          </div>
        </div>
        {preview ? (
          <div className="mt-2 min-h-[320px] rounded-xl border border-line bg-white p-5">
            {body.trim() ? <BlogBody text={body} /> : <p className="text-sm text-ink-soft">Nothing to preview yet.</p>}
          </div>
        ) : (
          <textarea id="blog-body" value={body} onChange={(e) => setBody(e.target.value)} maxLength={BODY_MAX} rows={16}
            placeholder={'Share your story...\n\nLeave a blank line between paragraphs.\n\n## Start a line with two hashes for a heading'}
            className="mt-2 w-full rounded-xl border border-line bg-white p-4 text-[15px] leading-relaxed text-ink outline-none focus:border-ember" />
        )}
        <p className="mt-1 text-right text-xs text-ink-soft">{body.length.toLocaleString()} / {BODY_MAX.toLocaleString()}</p>

        {error && <p className="mt-4 rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}

        <div className="mt-6 flex flex-wrap gap-3">
          <button type="submit" disabled={busy || uploading}
            className="flame-gradient rounded-full px-6 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 disabled:opacity-50">
            {busy ? 'Submitting...' : editing ? 'Save and resubmit' : 'Submit for review'}
          </button>
          <Link to="/blog" className="rounded-full border border-line px-6 py-2.5 text-sm font-semibold text-ink hover:bg-mist">Cancel</Link>
        </div>
      </form>
    </BlogShell>
  )
}
