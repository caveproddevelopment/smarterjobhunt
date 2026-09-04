import { useState } from 'react'
import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import SEO from '../components/SEO'
import { faqs } from '../data/faqs'

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState(0)

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <SEO
          title="JobBeggar FAQ - Pricing, Matching Score, and Cancellation"
          description="Answers to the most common JobBeggar questions: pricing, how the matching score works, company database size, and cancellations."
          path="/faq"
        />
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