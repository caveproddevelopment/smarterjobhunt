// Shared FAQ question/answer content -- used by both the standalone FAQ
// page (pages/FAQ.jsx) and the FAQ section on the landing page
// (pages/Landing.jsx), so the two never drift out of sync with each other.
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import SEO from '../components/SEO'
import { faqs } from '../data/faqs'

export default function FAQ() {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <SEO
          title="JobBeggar FAQ"
          description="Answers about JobBeggar's weekly subscription, job matching, and company career-page search."
          path="/faq"
        />
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">FAQ</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            Common questions
          </h1>
          <div className="mt-10 divide-y divide-line border-y border-line">
            {faqs.map((faq) => (
              <section key={faq.q} className="py-6">
                <h2 className="font-display text-lg font-semibold text-ink">{faq.q}</h2>
                <div className="mt-2 text-sm leading-relaxed text-ink-soft">{faq.a}</div>
              </section>
            ))}
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}