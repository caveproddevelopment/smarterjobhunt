import Navbar from '../components/Navbar'
import Footer from '../components/Footer'

export default function TermsOfService() {
  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">Legal</p>

          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            Terms of Service
          </h1>

          <p className="mt-3 text-sm text-ink-soft">Last updated: 8/27/2026</p>

          <div className="mt-8 space-y-6 text-base leading-relaxed text-ink-soft">
            <p>
              Welcome to JobBeggar.com ("JobBeggar," "we," "us," or "our"), operated by
              Caveman Productions Media LLC. These Terms of Service ("Terms") govern your
              use of JobBeggar.com and its related services (the "Service"). By using the
              Service, you agree to these Terms.
            </p>
            <p>If you do not agree to these Terms, please don't use the Service.</p>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                1. What JobBeggar Is
              </h2>
              <p className="mt-3">
                JobBeggar is a job search tool that aggregates publicly available job
                listings directly from company career pages and presents them to you in
                one place, matched against the job titles and companies you search for.
              </p>
              <p className="mt-3">
                JobBeggar is not a staffing agency, recruiter, or employer. We do not
                place candidates in jobs, guarantee interviews, guarantee employment, or
                act as an intermediary between you and any employer. We do not have an
                employment relationship with any of the companies whose listings appear
                on the Service. Any application you submit through a listing is
                submitted directly to that employer, subject to that employer's own
                process and terms.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">2. Accounts</h2>
              <p className="mt-3">
                You must provide accurate information when creating an account and keep
                your login credentials secure. You're responsible for all activity that
                happens under your account. If you believe your account has been
                accessed without authorization, contact us immediately at{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>
                .
              </p>
              <p className="mt-3">You must be at least 18 years old to use JobBeggar.</p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                3. Subscription and Billing
              </h2>
              <p className="mt-3">JobBeggar is offered on a subscription basis:</p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>Weekly plan: $3.99, billed every 7 days</li>
                <li>Monthly plan: $9.99, billed every 30 days</li>
              </ul>
              <p className="mt-3">
                No free trial is offered. Your subscription begins immediately upon
                payment.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Automatic renewal:</strong>{' '}
                Subscriptions renew automatically at the end of each billing period
                unless canceled before the renewal date. You authorize us (and our
                payment processor) to charge your payment method on file for each
                renewal.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Cancellation:</strong> You may
                cancel your subscription at any time through your account settings or by
                contacting{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>
                . Cancellation stops future billing but does not refund the current
                billing period already paid for, except where required by law.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Refunds:</strong> Payments are
                generally non-refundable. If you believe you were charged in error,
                contact{' '}
                <a href="mailto:support@jobbeggar.com" className="font-semibold text-ember hover:underline">
                  support@jobbeggar.com
                </a>{' '}
                and we'll review it.
              </p>
              <p className="mt-3">
                <strong className="font-semibold text-ink">Price changes:</strong> We may
                change subscription pricing. If we do, we'll provide notice before the
                change takes effect for existing subscribers.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                4. Acceptable Use
              </h2>
              <p className="mt-3">When using JobBeggar, you agree not to:</p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>Use the Service for any unlawful purpose</li>
                <li>
                  Attempt to scrape, copy, or redistribute the job listing data we've
                  aggregated for use in a competing product
                </li>
                <li>
                  Attempt to gain unauthorized access to our systems or another user's
                  account
                </li>
                <li>Interfere with or disrupt the Service or its underlying infrastructure</li>
                <li>
                  Use automated tools (bots, scripts) to access the Service outside of
                  its intended normal use
                </li>
                <li>
                  Misrepresent your identity or create multiple accounts to circumvent
                  billing or usage limits
                </li>
              </ul>
              <p className="mt-3">
                We reserve the right to suspend or terminate accounts that violate these
                terms.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                5. Job Listing Data
              </h2>
              <p className="mt-3">
                Job listings displayed on JobBeggar are gathered from publicly available
                company career pages. While we work to keep listings current and
                accurate:
              </p>
              <ul className="mt-3 list-disc space-y-2 pl-5">
                <li>
                  We do not guarantee that any listing is still open, accurately
                  described, or free of errors at the time you view it. Listings can
                  change or be removed by the employer at any time without our
                  knowledge.
                </li>
                <li>
                  We are not responsible for the accuracy, legality, or outcome of any
                  job listing, application, or hiring decision made by a third-party
                  employer.
                </li>
                <li>
                  Always verify details directly with the employer before making
                  decisions based on a listing.
                </li>
              </ul>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                6. Intellectual Property
              </h2>
              <p className="mt-3">
                The JobBeggar name, logo, website design, and underlying software are
                the property of Caveman Productions Media LLC and may not be copied,
                reproduced, or used without our permission. Job listing content itself
                is the property of the respective employers who posted it.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                7. Disclaimer of Warranties
              </h2>
              <p className="mt-3">
                The Service is provided "as is" and "as available," without warranties
                of any kind, express or implied. We do not guarantee that the Service
                will be uninterrupted, error-free, or that it will result in you
                obtaining employment.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                8. Limitation of Liability
              </h2>
              <p className="mt-3">
                To the fullest extent permitted by law, Caveman Productions Media LLC
                and JobBeggar will not be liable for any indirect, incidental, special,
                or consequential damages arising from your use of the Service,
                including but not limited to lost wages, lost job opportunities, or
                lost profits. Our total liability for any claim relating to the Service
                will not exceed the amount you paid us in the 3 months before the claim
                arose.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                9. Termination
              </h2>
              <p className="mt-3">
                You may stop using the Service and cancel your subscription at any
                time. We may suspend or terminate your access to the Service if you
                violate these Terms, or for any other reason with reasonable notice
                where practical.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                10. Changes to These Terms
              </h2>
              <p className="mt-3">
                We may update these Terms from time to time. If we make material
                changes, we'll update the "Last updated" date above and, where
                appropriate, notify you directly. Continued use of the Service after
                changes take effect means you accept the updated Terms.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                11. Governing Law
              </h2>
              <p className="mt-3">
                These Terms are governed by the laws of the State of Texas, without
                regard to conflict-of-law principles.
              </p>
            </section>

            <section className="border-t border-line pt-6">
              <h2 className="font-display text-xl font-semibold text-ink">
                12. Contact Us
              </h2>
              <p className="mt-3">
                Questions about these Terms? Email us at{' '}
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
