import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import LoopVisual from '../components/LoopVisual'

const reviews = [
  {
    quote:
      "I stopped keeping a spreadsheet. Every role from every seed-stage company I care about just shows up, ranked.",
    name: 'Priya N.',
    role: 'Product Manager, applied via SmarterJobHunt',
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
  const navigate = useNavigate()

  function handleSearch(event) {
    event.preventDefault()
    navigate(query ? `/dashboard?title=${encodeURIComponent(query)}` : '/dashboard')
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="px-6">
          {/* Hero */}
          <section className="mx-auto grid max-w-6xl items-center gap-14 py-10 md:grid-cols-2 md:py-16">
            <div>
              <span className="inline-block rounded-full bg-mist px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-ink-soft">
                Built for the startup job hunt
              </span>
              <h1 className="mt-6 font-display text-4xl font-bold leading-[1.1] text-ink md:text-5xl">
                Stop tab-hopping between fifty career pages.
              </h1>
              <p className="mt-5 max-w-md text-base leading-relaxed text-ink-soft">
                SmarterJobHunt pulls fresh roles from seed-to-Series-B startups into one
                list, scores each one against your resume, and remembers who you've
                applied to — so you don't have to.
              </p>

              <form onSubmit={handleSearch} className="mt-8 max-w-md">
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

            <LoopVisual />
          </section>

          {/* Video explainer */}
          <section id="what-is-this" className="mx-auto max-w-6xl py-10">
            <div className="flex aspect-video items-center justify-center rounded-2xl border border-line bg-mist">
              <div className="flex flex-col items-center gap-3 text-ink-soft">
                <span className="flex h-14 w-14 items-center justify-center rounded-full flame-gradient text-white">
                  ▶
                </span>
                <p className="text-sm font-medium">Product walkthrough — 90 seconds</p>
              </div>
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
