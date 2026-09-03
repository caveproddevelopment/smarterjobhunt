import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import SEO from '../components/SEO'

export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <SEO
          title="Privacy Policy - JobBeggar"
          description="Read JobBeggar's Privacy Policy to learn what data is collected, how it's used, and your rights as a user."
          path="/privacy"
        />
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">Legal</p>

          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            Privacy Policy
          </h1>

          <p className="mt-3 text-sm text-ink-soft">Last updated: 8/27/2026</p>

          <div className="mt-8 space-y-6 text-base leading-relaxed text-ink-soft">
            <p>
              JobBeggar.com ("JobBeggar," "we," "us," or "our") is operated by Caveman
              Productions Media LLC. This Privacy Policy explains what information we
              collect, how we use it, and the choices you have.
            </p>
            <p>By using JobBeggar.com, you agree to the practices described in this policy.</p>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                1. Information We Collect
              </h2>

              <p className="mt-3 font-semibold text-ink">Information you give us directly:</p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>Name and email address when you create an account</li>
                <li>
                  Payment information when you subscribe (processed by our third-party
                  payment processor — we do not store your full card number on our
                  servers)
                </li>
                <li>
                  Job search preferences, such as job titles, target companies, and
                  search history within the app
                </li>
                <li>Any information you send us directly, such as support requests</li>
              </ul>

              <p className="mt-5 font-semibold text-ink">
                Information we collect automatically:
              </p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>Basic usage data (pages visited, features used, general device/browser information)</li>
                <li>
                  Cookies and similar technologies used to keep you logged in and to
                  understand how the site is used
                </li>
              </ul>

              <p className="mt-5 font-semibold text-ink">
                Information we do not collect from you:
              </p>
              <p className="mt-3">
                We do not ask for your resume, social security number, or government ID
                to use the core search features.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                2. How We Use Your Information
              </h2>
              <p className="mt-3">We use the information we collect to:</p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>Provide and operate the job search service, including matching you with relevant job listings</li>
                <li>Process your subscription payments and manage your account</li>
                <li>Respond to support requests</li>
                <li>Improve and maintain the site</li>
                <li>Send you service-related communications (such as billing confirmations or important account notices)</li>
              </ul>
              <p className="mt-5">
                We do not use your information to send marketing emails unless you've
                opted in, and you can opt out of any non-essential communications at any
                time.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                3. How We Share Your Information
              </h2>
              <p className="mt-3">We do not sell your personal information.</p>
              <p className="mt-3">We may share information with:</p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>
                  <strong className="font-semibold text-ink">Service providers</strong>{' '}
                  who help us operate the site — for example, our payment processor (to
                  process subscription payments) and our hosting provider (to run the
                  site itself). These providers only receive the information necessary
                  to do their job.
                </li>
                <li>
                  <strong className="font-semibold text-ink">Legal reasons</strong> — if
                  required to comply with a law, regulation, legal process, or
                  governmental request.
                </li>
                <li>
                  <strong className="font-semibold text-ink">Business transfers</strong>{' '}
                  — if JobBeggar or Caveman Productions Media LLC is involved in a
                  merger, acquisition, or sale of assets, user information may be
                  transferred as part of that transaction. We'll notify you if this
                  happens.
                </li>
              </ul>
              <p className="mt-5">
                The job listing data shown on JobBeggar is gathered from publicly
                available company career pages — this is separate from your personal
                account information and is not tied to your identity.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                4. Your Choices and Rights
              </h2>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Access and correction:</strong>{' '}
                You can review and update your account information at any time by
                logging in.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Deletion:</strong> You can
                request that we delete your account and associated personal information
                by emailing{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>
                . We'll process deletion requests within a reasonable time, except where
                we're required to retain certain information for legal or accounting
                purposes (such as billing records).
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Cookies:</strong> Most
                browsers let you block or delete cookies. Doing so may affect how well
                the site works.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Marketing communications:</strong>{' '}
                You can unsubscribe from any marketing emails using the link in those
                emails.
              </p>
              <p className="mt-3">
                If you are located in a region with specific data protection rights
                (such as the EU/UK under GDPR, or California under the CCPA), you may
                have additional rights, including the right to know what data we hold
                about you and the right to request its deletion. Contact us at{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>{' '}
                to exercise these rights.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                5. Data Security
              </h2>
              <p className="mt-3">
                We take reasonable steps to protect your information, including
                encrypted connections and secure payment processing through a reputable
                third-party processor. No method of transmission or storage is 100%
                secure, and we cannot guarantee absolute security.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                6. Children's Privacy
              </h2>
              <p className="mt-3">
                JobBeggar is not directed at or intended for use by anyone under 18. We
                do not knowingly collect information from children. If we learn we've
                collected information from a child under 18, we will delete it.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                7. Changes to This Policy
              </h2>
              <p className="mt-3">
                We may update this Privacy Policy from time to time. If we make
                material changes, we'll update the "Last updated" date above and, where
                appropriate, notify you directly.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                8. Contact Us
              </h2>
              <p className="mt-3">
                Questions about this policy or your data? Email us at{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>
                .
              </p>
            </section>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}
