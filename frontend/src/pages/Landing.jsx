import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

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

export default function Landing() {
  const [query, setQuery] = useState('')
  const [isPlaying, setIsPlaying] = useState(false)
  const navigate = useNavigate()
  const videoBoxRef = useRef(null)

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
        setIsPlaying(false)
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [isPlaying])

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="px-6">
          {/* Hero: explanation + search on the left, video on the right */}
          <section
            id="what-is-this"
            className="mx-auto grid max-w-6xl items-start gap-10 py-10 md:grid-cols-2 md:py-16"
          >
            <div>
              <div className="max-w-md space-y-3 text-base leading-relaxed text-ink-soft">
                <p>Job boards suck.</p>
                <p>
                  They're full of reposts, expired listings, and jobs that
                  don't exist anymore.
                </p>
                <p>JobBeggar.com skips the boards and goes straight to the company.</p>
                <p>
                  JobBeggar.com does a better job using variants of your job
                  title to find all of the relevant jobs.
                </p>
                <p>
                  And JobBeggar.com allows you to target specific types of
                  companies like Funded startups, Fortune 500 and Major Indian
                  companies.
                </p>
                <p>The interface is easy and intuitive.</p>
                <p>You need a job. JobBeggar.com can help.</p>
              </div>

              <form onSubmit={handleSearch} className="mt-10 max-w-md">
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
            </div>

            <div
              ref={videoBoxRef}
              className="relative aspect-video overflow-hidden rounded-2xl border border-line bg-mist"
            >
              {isPlaying ? (
                <video
                  autoPlay
                  controls
                  playsInline
                  preload="metadata"
                  onEnded={() => setIsPlaying(false)}
                  className="h-full w-full object-contain"
                >
                  <source src="/videos/walkthrough.mp4" type="video/mp4" />
                  Your browser doesn't support embedded video.
                </video>
              ) : (
                <button
                  type="button"
                  onClick={() => setIsPlaying(true)}
                  aria-label="Play walkthrough video"
                  className="group flex h-full w-full flex-col items-center justify-center gap-3 bg-mist text-ink-soft"
                >
                  <span className="flex h-14 w-14 items-center justify-center rounded-full flame-gradient text-white shadow-lg transition-transform group-hover:scale-105">
                    ▶
                  </span>
                  <span className="text-sm font-medium">Product walkthrough — 90 seconds</span>
                </button>
              )}
            </div>
          </section>

          {/* Reviews */}
          <section className="mx-auto max-w-6xl py-10 pb-16">
            <h2 className="font-display text-2xl font-semibold text-ink">
              Job seekers who closed the loop
            </h2>
            <div className="mt-8 grid gap-6 md:grid-cols-3">
              {reviews.map((review) => (
                <article
                  key={review.name}
                  className="rounded-2xl border border-line bg-white p-6 shadow-sm"
                >
                  <span className="font-display text-3xl flame-text-gradient">“</span>
                  <p className="mt-1 text-sm leading-relaxed text-ink">{review.quote}</p>
                  <p className="mt-5 text-sm font-semibold text-ink">{review.name}</p>
                  <p className="text-xs text-ink-soft">{review.role}</p>
                </article>
              ))}
            </div>
          </section>
        </main>

        <Footer />
      </div>
    </div>
  )
}