// Small pieces shared by The JobBeggar Brief pages (Blog, BlogPost, BlogEditor).
import { Link } from 'react-router-dom'
import Navbar from './Navbar'
import Footer from './Footer'
import { formatDate, imageUrl } from '../lib/blogApi'

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
        <h2 className="font-display text-lg font-semibold leading-snug text-ink group-hover:text-ember">
          {post.title}
        </h2>
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-ink-soft">{post.excerpt}</p>
        <div className="mt-auto flex items-center justify-between gap-3 pt-5 text-xs text-ink-soft">
          <span className="flex min-w-0 items-center gap-2">
            <Avatar initials={post.author.initials} size="h-7 w-7 text-[10px]" />
            <span className="truncate">
              {post.author.name} · {formatDate(post.published_at || post.updated_at)}
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
