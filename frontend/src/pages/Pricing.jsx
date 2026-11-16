import { Link } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import SEO from '../components/SEO'
import { useAuth } from '../lib/auth'

// JobBeggar is free. This page stays at /pricing so old links and search
// results still land somewhere that says so.
export default function Pricing() {
  const { user } = useAuth()

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <SEO
          title="JobBeggar is free"
          description="JobBeggar is free: no subscription, no trial, no card. Direct access to company career pages ranked by match score."
          path="/pricing"
        />
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">Pricing</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            JobBeggar is free.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">
            No subscription, no trial, no card. Make an account and you get full access to every
            listing.
          </p>

          <div className="mt-10 flex flex-col rounded-2xl border border-line bg-white p-6 shadow-sm sm:max-w-sm">
            <h2 className="font-display text-lg font-semibold text-ink">Everything</h2>
            <p className="mt-3">
              <span className="font-display text-3xl font-semibold flame-text-gradient">$0</span>
            </p>
            <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-soft">
              Search every company, see full job details, and apply straight on the company's own
              career page.
            </p>
            <Link
              to={user ? '/dashboard' : '/login'}
              className="mt-6 rounded-full flame-gradient py-2.5 text-center text-sm font-semibold text-white transition-transform hover:scale-[1.02]"
            >
              {user ? 'Go to job listings' : 'Sign up free'}
            </Link>
          </div>

          {user?.plan === 'pro' && (
            <p className="mt-6 text-sm text-ink-soft">
              Still have an old paid subscription?{' '}
              <Link to="/profile" className="font-semibold text-ember hover:underline">
                Cancel it from your profile
              </Link>{' '}
              — you no longer need it.
            </p>
          )}
        </main>

        <Footer />
      </div>
    </div>
  )
}
