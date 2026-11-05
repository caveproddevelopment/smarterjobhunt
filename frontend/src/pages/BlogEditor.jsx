import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import SEO from '../components/SEO'
import { BlogShell, RichBody, plainTextToHtml } from '../components/BlogParts'
import RichEditor from '../components/RichEditor'
import {
  createPost, fetchBlogMe, fetchCategories, fetchPost, imageUrl, postIdFromParam, updatePost, uploadImage,
} from '../lib/blogApi'
import { useAuth } from '../lib/auth'

const TITLE_MAX = 150
const SUBTITLE_MAX = 200
const CATEGORY_MAX = 40
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
  const [subtitle, setSubtitle] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState([])
  const [bodyHtml, setBodyHtml] = useState('')
  const [bodyText, setBodyText] = useState('')
  const [republish, setRepublish] = useState(false)
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
    fetchCategories().then(setCategories).catch(() => {})
  }, [])

  useEffect(() => {
    if (!editing) return
    fetchPost(postId)
      .then((p) => {
        setTitle(p.title)
        setSubtitle(p.subtitle || '')
        setCategory(p.category || '')
        // older plain-text posts open in the rich editor as paragraphs
        setBodyHtml(p.body_html || plainTextToHtml(p.body))
        setBodyText(p.body)
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
    if (bodyText.trim().length < BODY_MIN) return setError(`Post must be at least ${BODY_MIN} characters.`)
    if (bodyText.length > BODY_MAX) return setError(`Post must be at most ${BODY_MAX.toLocaleString()} characters.`)
    setBusy(true)
    try {
      const payload = { title, subtitle, category, body_html: bodyHtml, republish: editing && republish, cover_image_id: cover?.id || null }
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
          <p className="rounded-2xl border border-line bg-mist p-5 text-sm text-ink-soft">
            Posts on The JobBeggar Brief are written by the JobBeggar team.{' '}
            <Link to="/blog" className="font-semibold text-ember hover:underline">Read the latest posts</Link>
          </p>
        </div>
      </BlogShell>
    )
  }

  return (
    <BlogShell>
      <SEO title={editing ? 'Edit post | The JobBeggar Brief' : 'Write a post | The JobBeggar Brief'} path="/blog/new" />
      <form onSubmit={onSubmit} className="mx-auto max-w-3xl py-6">
        <Link to="/blog" className="text-sm font-semibold text-ink-soft hover:text-ink">&larr; The JobBeggar Brief</Link>
        <h1 className="mt-4 font-display text-3xl font-semibold text-ink">{editing ? 'Edit post' : 'Write a post'}</h1>
        <p className="mt-2 text-sm text-ink-soft">
          {editing ? 'Changes go live as soon as you save.' : 'Your post goes live on The JobBeggar Brief as soon as you publish.'}
        </p>

        <label className="mt-8 block text-sm font-semibold text-ink" htmlFor="blog-title">Title</label>
        <input id="blog-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={TITLE_MAX}
          placeholder="Org charts before brick and mortar"
          className="mt-2 w-full rounded-xl border border-line bg-white px-4 py-3 font-display text-xl text-ink outline-none focus:border-ember" />

        <label className="mt-6 block text-sm font-semibold text-ink" htmlFor="blog-category">Category (optional)</label>
        <input id="blog-category" list="blog-categories" value={category} onChange={(e) => setCategory(e.target.value)}
          maxLength={CATEGORY_MAX} placeholder="Healthcare"
          className="mt-2 w-full rounded-xl border border-line bg-white px-4 py-3 text-ink outline-none focus:border-ember sm:w-72" />
        <datalist id="blog-categories">
          {categories.map((c) => <option key={c.name} value={c.name} />)}
        </datalist>
        <p className="mt-1 text-xs text-ink-soft">Pick an existing one or type a new one. Shown as &ldquo;HEALTHCARE · NOV 2026&rdquo;.</p>

        <label className="mt-6 block text-sm font-semibold text-ink" htmlFor="blog-subtitle">Subtitle (optional)</label>
        <input id="blog-subtitle" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} maxLength={SUBTITLE_MAX}
          placeholder="LifeStance's specialty expansion takes shape"
          className="mt-2 w-full rounded-xl border border-line bg-white px-4 py-3 text-lg text-ink outline-none focus:border-ember" />

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
          <span className="text-sm font-semibold text-ink">Post</span>
          <div className="flex rounded-full border border-line p-0.5 text-xs font-semibold">
            {[[false, 'Write'], [true, 'Preview']].map(([value, label]) => (
              <button key={label} type="button" onClick={() => setPreview(value)}
                className={`rounded-full px-3 py-1 ${preview === value ? 'bg-ink text-white' : 'text-ink-soft'}`}>{label}</button>
            ))}
          </div>
        </div>
        {preview ? (
          <div className="mt-2 min-h-[320px] rounded-xl border border-line bg-white p-5">
            {bodyText.trim() ? <RichBody html={bodyHtml} /> : <p className="text-sm text-ink-soft">Nothing to preview yet.</p>}
          </div>
        ) : null}
        {/* kept mounted while previewing so undo history and cursor survive */}
        <div className={preview ? 'hidden' : 'mt-2'}>
          <RichEditor value={bodyHtml} onChange={(html, text) => { setBodyHtml(html); setBodyText(text) }} />
        </div>
        <p className="mt-1 text-right text-xs text-ink-soft">{bodyText.length.toLocaleString()} / {BODY_MAX.toLocaleString()}</p>

        {editing && (
          <label className="mt-4 flex items-start gap-3 rounded-xl border border-line bg-white p-4 text-sm text-ink">
            <input type="checkbox" checked={republish} onChange={(e) => setRepublish(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-ember" />
            <span>
              <span className="font-semibold">Republish now</span>
              <span className="block text-ink-soft">
                Moves this post back to the top of The Brief with today&rsquo;s date. Leave unticked to just save your edits.
              </span>
            </span>
          </label>
        )}

        {error && <p className="mt-4 rounded-xl bg-ember/10 p-3 text-sm text-ember">{error}</p>}

        <div className="mt-6 flex flex-wrap gap-3">
          <button type="submit" disabled={busy || uploading}
            className="flame-gradient rounded-full px-6 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 disabled:opacity-50">
            {busy ? 'Saving...' : editing ? (republish ? 'Save and republish' : 'Save changes') : 'Publish'}
          </button>
          <Link to="/blog" className="rounded-full border border-line px-6 py-2.5 text-sm font-semibold text-ink hover:bg-mist">Cancel</Link>
        </div>
      </form>
    </BlogShell>
  )
}
