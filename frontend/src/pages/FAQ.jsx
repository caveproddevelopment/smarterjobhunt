import { useState } from 'react'
import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

const faqs = [
  {
    q: 'Why no free tier?',
    a: "I built something of real value here — advertising income is basically meaningless, and it wouldn't come close to covering what this actually costs to run. If you see the value in using this site, the subscription is pretty tiny. If you want free, go check out those \"fun and useful\" job boards.",
  },
  {
    q: 'How many companies are there?',
    a: "We're always adding company databases. Each set — Fortune 500, Funded Startups, Health Care, Major Indian Companies, Mid-sized US — runs anywhere from 500 to 2,000 companies. There's a bit of overlap between some of them, too — a company can land in both Mid-sized and Funded, or Health Care and Fortune 500, for example.",
  },
  {
    q: 'How reliable is the matching score?',
    a: "For what it is, the matching score is exact — it's not a fuzzy guess, it's math, and here's the actual rule. We score every job two ways: how well your search words show up in the title, and how well they show up in the full job description. If a job's title (or one of the 15 title variants we also check) contains your exact search phrase, that side scores a full 100%. Otherwise, each word you typed counts for an equal share of 100%, and the title only earns credit for the words it actually contains. A job only makes it into your results if the title side or the description side clears 50% on its own — and whichever one cleared that bar is the percentage shown on the card. It's never a blended average, so the number you see always matches the actual reason the job showed up. Match every single word in both the title and the description, and the job gets marked a Perfect Match and jumps to the top of the list, newest first. If you're logged in, you'll also see a personalized AI match score on jobs — that one's calculated separately, comparing your profile against the listing on its own schedule behind the scenes.",
  },
  {
    q: 'Can I cancel anytime?',
    a: "Of course. There's no trap. You pay for either a week or a month. If you're job hunting, locking into anything longer than a month is kind of silly anyway. Cancel anytime.",
  },
  {
    q: 'What happens if I find a broken listing?',
    a: (
      <>
        Please reach out to me at{' '}
        <a
          href="mailto:support@jobbeggar.com"
          className="font-semibold text-ember hover:underline"
        >
          support@jobbeggar.com
        </a>
        . We're not perfect — trust me, I have a wife and kids who remind me of that daily. When we
        hear about a bad listing, we look into why it happened and put a rule in place to keep it
        from happening again.
      </>
    ),
  },
]

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState(0)

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">FAQ</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            Questions people actually ask
          </h1>
          <p className="mt-4 text-base leading-relaxed text-ink-soft">
            Straight answers, no runaround. Can't find what you're looking for?{' '}
            <Link to="/about#contact" className="font-semibold text-ember hover:underline">
              Send us a message
            </Link>
            .
          </p>

          <div className="mt-10 space-y-3">
            {faqs.map((faq, index) => {
              const isOpen = openIndex === index
              return (
                <div
                  key={faq.q}
                  className="overflow-hidden rounded-2xl border border-line bg-white shadow-sm"
                >
                  <button
                    type="button"
                    onClick={() => setOpenIndex(isOpen ? null : index)}
                    aria-expanded={isOpen}
                    className="flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
                  >
                    <span className="font-display text-base font-semibold text-ink">{faq.q}</span>
                    <span
                      aria-hidden
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full flame-gradient text-sm font-bold text-white transition-transform ${
                        isOpen ? 'rotate-45' : ''
                      }`}
                    >
                      +
                    </span>
                  </button>

                  {isOpen && (
                    <div className="px-6 pb-6 text-sm leading-relaxed text-ink-soft">{faq.a}</div>
                  )}
                </div>
              )
            })}
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}
