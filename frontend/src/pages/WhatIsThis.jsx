import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import SEO from '../components/SEO'

const features = [
  {
    title: 'Straight to the source',
    body: "Instead of pulling from other job boards, we check each company's own career page — or wherever they actually run hiring: Greenhouse, Lever, Ashby, or Workable.",
  },
  {
    title: 'Live, not stale',
    body: "We pull listings directly through those systems. What you're looking at is what the company has posted right now, not a copy from three weeks ago.",
  },
  {
    title: 'Pick your company type',
    body: 'We search specific databases — like our "Funded Startups" and "Fortune 500" lists — and keep adding more, so you can choose the kind of company you actually want to work for.',
  },
  {
    title: 'Smarter title matching',
    body: "Search isn't limited to the exact words a company used. For every title you enter, we check 15 variants a company might use for the same role.",
  },
]

const variants = [
  'Product Owner',
  'Senior Product Manager',
  'Associate Product Manager',
  'Digital Product Manager',
  'Technical Product Manager',
  'Group Product Manager',
  'Principal Product Manager',
  'Project Lead',
  'Project Strategist',
  'Platform Project Manager',
  'Project Manager II',
  'Director of Product Management',
  'Growth Product Manager',
  'Product Operations Manager',
  'Program Manager',
]

export default function WhatIsThis() {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <SEO
          title="What is JobBeggar? - How It Works"
          description="JobBeggar searches company career pages directly instead of job boards, checking 15 title variants per search so you never miss a role because of how it's titled."
          path="/what-is-this"
        />
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">What is this?</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            You need a job. This is the tool built to help you find one.
          </h1>

          <div className="mt-6 space-y-5 text-base leading-relaxed text-ink-soft">
            <p>
              Most job boards are middlemen. They collect postings from somewhere else, dress them up
              with a match score, and hope you apply enough times that one sticks. Half the listings
              are already filled. The other half were never posted directly by the company in the
              first place — they were scraped, re-scraped, and stripped of anything useful along the
              way.
            </p>
            <p>
              JobBeggar works differently because it was built to solve a real, specific problem: I
              was job hunting after being laid off from a major tech company, and the tools I was
              using kept wasting my time. So I built the tool I actually wanted — and liked it enough
              to turn it into this for everyone.
            </p>
          </div>

          <div className="mt-12 grid gap-6 sm:grid-cols-2">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="rounded-2xl border border-line bg-white p-6 shadow-sm"
              >
                <h2 className="font-display text-lg font-semibold text-ink">{feature.title}</h2>
                <p className="mt-2 text-sm leading-relaxed text-ink-soft">{feature.body}</p>
              </div>
            ))}
          </div>

          <div className="mt-12 rounded-2xl border border-line bg-mist p-6">
            <p className="text-sm font-semibold text-ink">One search, fifteen ways to say it</p>
            <p className="mt-1 text-sm text-ink-soft">
              For every job title you provide, JobBeggar looks for the other titles a company might
              use to post the same role. Search "Project Manager" and we also check for:
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {variants.map((variant) => (
                <span
                  key={variant}
                  className="rounded-full border border-line bg-white px-3 py-1 text-xs font-medium text-ink-soft"
                >
                  {variant}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-12 border-t border-line pt-8">
            <h2 className="font-display text-lg font-semibold text-ink">What this is not</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-soft">
              A promise. JobBeggar doesn't guarantee an interview, a callback, or a job. What it does
              is put you closer to the actual source of the listing — faster, with less noise between
              you and the "Apply" button.
            </p>
          </div>

          <div className="mt-12 flex flex-wrap items-center gap-4">
            <Link
              to="/dashboard"
              className="rounded-full flame-gradient px-6 py-3 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
            >
              Browse open roles
            </Link>
            <Link to="/pricing" className="text-sm font-semibold text-ink-soft hover:text-ink">
              See pricing →
            </Link>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}
