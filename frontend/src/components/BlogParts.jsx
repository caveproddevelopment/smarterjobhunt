// Small pieces shared by The JobBeggar Brief pages (Blog, BlogPost, BlogEditor).
import DOMPurify from 'dompurify'
import { Link } from 'react-router-dom'
import Navbar from './Navbar'
import Footer from './Footer'
import { imageUrl, kickerLabel } from '../lib/blogApi'

export function BlogShell({ children }) {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto flex min-h-screen max-w-6xl flex-col bg-paper shadow-2xl shadow-ink/10">
        <Navbar />
        <main className="flex-1 px-4 pb-16 pt-4 sm:px-6">{children}</main>
        <Footer />
      </div>
    </div>
  )
}

// Post bodies are plain text: blank lines split paragraphs, "## " lines are
// headings. Rendered as text nodes, so user content can never inject HTML.
export function BlogBody({ text }) {
  const blocks = String(text || '').split(/\n{2,}/).map((b) => b.trim()).filter(Boolean)
  return (
    <div className="space-y-5 text-[17px] leading-relaxed text-ink">
      {blocks.map((block, i) =>
        block.startsWith('## ') ? (
          <h2 key={i} className="pt-2 font-display text-2xl font-semibold text-ink">
            {block.slice(3)}
          </h2>
        ) : (
          <p key={i} className="whitespace-pre-line">
            {block}
          </p>
        ),
      )}
    </div>
  )
}

// Same allowlist as backend/blog_html.py. The server already sanitized the
// HTML; this second pass means a bad row in the database still can't run code.
const ALLOWED_STYLE = /^(color|font-size|font-family|font-weight)$/
DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  if (data.attrName === 'style') {
    data.attrValue = data.attrValue
      .split(';')
      .map((d) => d.trim())
      .filter((d) => {
        const [prop, ...rest] = d.split(':')
        const val = rest.join(':').trim().toLowerCase()
        return prop && ALLOWED_STYLE.test(prop.trim().toLowerCase()) && !/url\(|expression|javascript/.test(val)
      })
      .join('; ')
  }
  if (data.attrName === 'target' && data.attrValue !== '_blank') data.keepAttr = false
})
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  // every link in an article opens in a new tab, safely
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

export function RichBody({ html }) {
  const safe = DOMPurify.sanitize(html || '', {
    ALLOWED_TAGS: ['p', 'br', 'h2', 'h3', 'strong', 'b', 'em', 'i', 'u', 's', 'a', 'ul', 'ol', 'li',
      'blockquote', 'span', 'hr'],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'style'],
    ALLOWED_URI_REGEXP: /^(https?:|mailto:)/i,
  })
  return <div className="brief-content" dangerouslySetInnerHTML={{ __html: safe }} />
}

// Older plain-text posts -> HTML for the rich editor ("## " lines become headings).
export function plainTextToHtml(text) {
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return String(text || '')
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean)
    .map((b) => (b.startsWith('## ') ? `<h2>${esc(b.slice(3))}</h2>` : `<p>${esc(b).replace(/\n/g, '<br>')}</p>`))
    .join('')
}

export function Avatar({ initials, size = 'h-9 w-9 text-xs' }) {
  return (
    <span
      className={`flame-gradient inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white ${size}`}
    >
      {initials}
    </span>
  )
}

export function HeartIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
      <path strokeLinejoin="round"
        d="M12 20.5s-7.5-4.6-9.3-9.2C1.5 8.1 3.6 4.5 7.1 4.5c2 0 3.6 1.1 4.9 2.9 1.3-1.8 2.9-2.9 4.9-2.9 3.5 0 5.6 3.6 4.4 6.8-1.8 4.6-9.3 9.2-9.3 9.2z" />
    </svg>
  )
}

export function CommentIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2">
      <path strokeLinejoin="round" d="M4 5h16v11H9l-5 4V5z" />
    </svg>
  )
}

export function PostCard({ post }) {
  const cover = imageUrl(post.cover_url)
  return (
    <Link
      to={post.path}
      className="group flex flex-col overflow-hidden rounded-2xl border border-line bg-white transition-shadow hover:shadow-lg hover:shadow-ink/5"
    >
      {cover ? (
        <img src={cover} alt="" loading="lazy" className="aspect-[16/9] w-full object-cover" />
      ) : (
        <div className="flame-gradient aspect-[16/9] w-full opacity-80" />
      )}
      <div className="flex flex-1 flex-col p-5">
        <p className="mb-2 font-mono text-[11px] font-semibold tracking-[0.12em] text-ember">{kickerLabel(post)}</p>
        <h2 className="font-display text-lg font-semibold leading-snug text-ink group-hover:text-ember">
          {post.title}
        </h2>
        {post.subtitle && (
          <p className="mt-1 text-sm font-medium leading-snug text-ink">{post.subtitle}</p>
        )}
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-ink-soft">{post.excerpt}</p>
        <div className="mt-auto flex items-center justify-between gap-3 pt-5 text-xs text-ink-soft">
          <span className="flex min-w-0 items-center gap-2">
            <Avatar initials={post.author.initials} size="h-7 w-7 text-[10px]" />
            <span className="truncate">
              {post.author.name}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-3">
            <span className="flex items-center gap-1"><HeartIcon filled={post.liked_by_me} />{post.like_count}</span>
            <span className="flex items-center gap-1"><CommentIcon />{post.comment_count}</span>
          </span>
        </div>
      </div>
    </Link>
  )
}

export function SubscribePrompt({ loggedIn, action = 'comment on and like posts' }) {
  return (
    <div className="rounded-2xl border border-line bg-mist p-5 text-sm text-ink-soft">
      {loggedIn ? (
        <>
          Subscribers can {action}.{' '}
          <Link to="/pricing" className="font-semibold text-ember hover:underline">See plans</Link>
        </>
      ) : (
        <>
          <Link to="/login" className="font-semibold text-ember hover:underline">Log in</Link> as a subscriber
          to {action}.
        </>
      )}
    </div>
  )
}
