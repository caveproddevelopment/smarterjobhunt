import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import FlipCounter from '../components/FlipCounter'
import { fetchSiteStats } from '../lib/api'
import { useCountUp } from '../lib/useCountUp'

// `type` is the company_type value the Job Listings page filters on when a
// badge is clicked (see companyTypes.js -- kept in sync with the backend's
// COMPANY_TYPES allowlist in routes/jobs.py).
const badges = [
  { src: '/images/badges/Fortune500.png', alt: 'Fortune 500 companies', type: 'fortune500' },
  { src: '/images/badges/FundedStartups.png', alt: 'Funded startups', type: 'funded' },
  { src: '/images/badges/HealthCare.png', alt: 'Health care companies', type: 'healthcare' },
  { src: '/images/badges/majorIndian.png', alt: 'Major Indian companies', type: 'indianmajor' },
  { src: '/images/badges/midsizedUS.png', alt: 'Mid-sized US companies', type: 'midsize' },
]

const reviews = [
  {
    quote:
      "I stopped keeping a spreadsheet. Every role from every seed-stage company I care about just shows up, ranked.",
    name: 'Priya N.',
    role: 'Product Manager, applied via JobBeggar',
  },
  {
    quote:
      "The match score actually saved me time — I stopped opening postings that were never going to fit.",
    name: 'Daniel O.',
    role: 'Backend Engineer',
  },
  {
    quote:
      "Filtering by funding stage alone was worth it. I only wanted Series A teams, and that's all I saw.",
    name: 'Marisol T.',
    role: 'Growth Marketer',
  },
]

const faqs = [
  { q: 'Why no free tier?' },
  { q: 'How many companies are there?' },
  { q: 'How reliable is the matching score?' },
  { q: 'Can I cancel anytime?' },
  { q: 'What happens if I find a broken listing?' },
]

export default function Landing() {
  const [query, setQuery] = useState('')
  const [isPlaying, setIsPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const navigate = useNavigate()
  const [stats, setStats] = useState({ companyCount: 0, jobCount: 0 })
  const animatedCompanyCount = useCountUp(stats.companyCount)
  const animatedJobCount = useCountUp(stats.jobCount)
  const videoBoxRef = useRef(null)
  // Tracks whether the person has manually played/dismissed the video, so
  // the 5-second auto-preview below doesn't override a choice they already
  // made (e.g. re-opening a video they just closed).
  const hasInteractedRef = useRef(false)

  function handleSearch(event) {
    event.preventDefault()
    navigate(query ? `/dashboard?title=${encodeURIComponent(query)}` : '/dashboard')
  }

  // Reset back to the cover state on an outside click while the video is
  // playing -- listener is only attached while isPlaying is true, so a click
  // anywhere before/after playback is a no-op.
  useEffect(() => {
    if (!isPlaying) return

    function handleOutsideClick(event) {
      if (videoBoxRef.current && !videoBoxRef.current.contains(event.target)) {
        hasInteractedRef.current = true
        setIsPlaying(false)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [isPlaying])

  // Fetch the site-wide company/job totals once on mount to drive the
  // counters at the top of the page; left at 0 (no animation) on failure.
  useEffect(() => {
    let cancelled = false
    fetchSiteStats()
      .then((data) => {
        if (!cancelled) setStats(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  // Auto-start the walkthrough preview 5 seconds after the page loads,
  // unless the person has already played or dismissed it themselves.
  // Starts muted so browsers allow the autoplay without a click; native
  // video controls let them unmute.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!hasInteractedRef.current) {
        setIsMuted(true)
        setIsPlaying(true)
      }
    }, 5000)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-10 gap-y-1 px-6 pb-2 text-center">
          <p className="flex items-center gap-2 font-display text-sm font-semibold text-ink">
            Current Company Count <FlipCounter value={animatedCompanyCount} />
          </p>
          <p className="flex items-center gap-2 font-display text-sm font-semibold text-ink">
            Current Job Count <FlipCounter value={animatedJobCount} />
          </p>
        </div>

        <main className="px-6">
          {/* Hero: heading, company badges, and the "why us" explainer */}
          <section id="what-is-this" className="mx-auto max-w-6xl pt-2 pb-10 md:pt-6 md:pb-16">
            <div className="mx-auto max-w-2xl text-center">
              <h1 className="font-display text-2xl text-ink-soft md:text-3xl">
                Pick the companies you'd actually work for
                <br />
                We'll dig up the jobs.
              </h1>

              <div className="mx-auto mt-8 flex w-full max-w-xl flex-wrap items-center justify-between gap-4">
                {badges.map((badge) => (
                  <button
                    key={badge.alt}
                    type="button"
                    onClick={() => navigate(`/dashboard?company_type=${badge.type}`)}
                    aria-label={`Browse ${badge.alt} jobs`}
                    className="shrink-0 transition-transform hover:scale-[1.05]"
                  >
                    <img src={badge.src} alt={badge.alt} className="h-36 w-auto sm:h-44" />
                  </button>
                ))}
              </div>

              <div className="mt-8 flex items-center justify-center gap-4">
                <span className="h-1 w-8 rounded-full bg-line sm:w-12" aria-hidden />
                <p className="font-display text-[1.6875rem] italic text-[#019c58]">
                  One Day Free No Card No Catch
                </p>
                <span className="h-1 w-8 rounded-full bg-line sm:w-12" aria-hidden />
              </div>

              <p className="mt-6 font-display text-xl text-ink-soft">
                Job Boards are <span className="text-ink">GARBAGE!</span>&nbsp;&nbsp;Skip 'em
              </p>
            </div>

            {/* Explainer copy on the left, search + video walkthrough on the right */}
            <div className="mx-auto mt-10 grid max-w-4xl items-start gap-10 md:grid-cols-2">
              <div className="mx-auto max-w-sm space-y-4 text-center text-sm leading-relaxed text-ink-soft">
                <p>Job boards suck.</p>
                <p>
                  They're full of reposts, expired listings, and jobs that{' '}
                  <span className="font-semibold text-ink">NEVER</span> existed.
                </p>
                <p>JobBeggar.com skips the boards and goes straight to the company.</p>
                <div className="!mt-6 rounded-sm bg-[#5c1717] px-6 py-3 text-sm font-semibold text-white">
                  You need a job and JobBeggar.com can help
                </div>
              </div>

              <div className="mx-auto flex w-full max-w-sm flex-col gap-4">
                <form onSubmit={handleSearch}>
                  <label htmlFor="job-title" className="text-sm font-medium text-ink">
                    Search for a job title
                  </label>
                  <div className="mt-2 flex items-center gap-2 rounded-full border border-line bg-white p-1.5 pl-5 shadow-sm">
                    <input
                      id="job-title"
                      type="text"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="e.g. Product Designer"
                      className="w-full bg-transparent text-sm text-ink placeholder:text-ink-soft/60 focus:outline-none"
                    />
                    <button
                      type="submit"
                      className="flex shrink-0 items-center gap-1 rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.03]"
                    >
                      Go <span aria-hidden>→</span>
                    </button>
                  </div>
                </form>

                <div
                  ref={videoBoxRef}
                  className="relative aspect-[5/4] overflow-hidden rounded-2xl border border-line bg-ink"
                >
                  {isPlaying ? (
                    <video
                      autoPlay
                      controls
                      playsInline
                      muted={isMuted}
                      preload="metadata"
                      poster="/images/WatchThisThmbnail.png"
                      onEnded={() => setIsPlaying(false)}
                      className="h-full w-full object-contain"
                    >
                      <source src="/videos/walkthrough.mp4" type="video/mp4" />
                      Your browser doesn't support embedded video.
                    </video>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        hasInteractedRef.current = true
                        setIsMuted(false)
                        setIsPlaying(true)
                      }}
                      aria-label="Play walkthrough video"
                      className="group relative block h-full w-full"
                    >
                      <img
                        src="/images/WatchThisThmbnail.png"
                        alt="How does this work? Watch this."
                        className="h-full w-full object-cover"
                      />
                      <span className="absolute inset-0 flex items-center justify-center bg-ink/0 transition-colors group-hover:bg-ink/20">
                        <span className="flex h-14 w-14 items-center justify-center rounded-full flame-gradient text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                          ▶
                        </span>
                      </span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          </section>

          {/* Reviews */}
          <section className="mx-auto max-w-6xl py-10">
            <h2 className="font-display text-2xl font-semibold text-ink">
              Job seekers who closed the loop
            </h2>
            <div className="mt-8 grid gap-6 md:grid-cols-3">
              {reviews.map((review) => (
                <article
                  key={review.name}
                  className="rounded-2xl border border-line bg-white p-6 shadow-sm"
                >
                  <span className="font-display text-3xl flame-text-gradient">"</span>
                  <p className="mt-1 text-sm leading-relaxed text-ink">{review.quote}</p>
                  <p className="mt-5 text-sm font-semibold text-ink">{review.name}</p>
                  <p className="text-xs text-ink-soft">{review.role}</p>
                </article>
              ))}
            </div>
          </section>

          {/* FAQ */}
          <section id="faq" className="mx-auto max-w-6xl py-10 pb-16">
            <h2 className="font-display text-lg font-semibold text-ink">FAQ</h2>
            <dl className="mt-6 space-y-6">
              {faqs.map((faq) => (
                <div key={faq.q}>
                  <dt className="text-sm text-ink">'{faq.q}'</dt>
                  <dd className="mt-2 text-sm text-ink-soft">{faq.a}</dd>
                </div>
              ))}
            </dl>
          </section>
        </main>

        <Footer />
      </div>
    </div>
  )
}