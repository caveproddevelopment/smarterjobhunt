import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import { useAuth } from '../lib/auth'

const plans = [
  {
    id: 'week',
    name: 'Weekly',
    price: '$3.99',
    cadence: '/ week',
    blurb:
      "You're that awesome, and so are we. You'll have that job before your next bill collector calls.",
  },
  {
    id: 'month',
    name: 'Monthly',
    price: '$9.99',
    cadence: '/ month',
    blurb: 'The more realistic, easier-on-your-budget decision.',
  },
]

export default function Pricing() {
  const { user, startCheckout, openBillingPortal } = useAuth()
  const navigate = useNavigate()
  const [loadingPlan, setLoadingPlan] = useState(null)
  const [portalLoading, setPortalLoading] = useState(false)
  const [error, setError] = useState(null)

  const isSubscribed = user?.plan === 'pro'

  // Clicking "Choose weekly/monthly" or "Manage subscription" navigates the
  // browser away to Stripe. If the user hits the back button, some browsers
  // (Chrome, Firefox, Safari) restore this page from the back/forward cache
  // instead of remounting it -- so the loading state from before the redirect
  // would otherwise be stuck showing "Redirecting…" / "Opening…" forever.
  // `pageshow` with `persisted: true` fires specifically on that bfcache
  // restore, so reset both loading flags then.
  useEffect(() => {
    function handlePageShow(event) {
      if (event.persisted) {
        setLoadingPlan(null)
        setPortalLoading(false)
      }
    }
    window.addEventListener('pageshow', handlePageShow)
    return () => window.removeEventListener('pageshow', handlePageShow)
  }, [])

  async function handleChoose(planId) {
    if (!user) {
      navigate('/login')
      return
    }
    setError(null)
    setLoadingPlan(planId)
    try {
      await startCheckout(planId) // redirects to Stripe on success
    } catch (err) {
      setError(err.message)
      setLoadingPlan(null)
    }
  }

  async function handleManageBilling() {
    setError(null)
    setPortalLoading(true)
    try {
      await openBillingPortal() // redirects to Stripe on success
    } catch (err) {
      setError(err.message)
      setPortalLoading(false)
    }
  }

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="mx-auto max-w-3xl px-6 py-16">
          <p className="text-sm font-semibold uppercase tracking-wide text-ember">Pricing</p>
          <h1 className="mt-2 font-display text-3xl font-semibold text-ink md:text-4xl">
            JobBeggar is going to make you make a choice.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft">
            We give you a day to see how valuable this tool is. Then you choose.
          </p>

          {error && <p className="mt-4 text-sm text-ember">{error}</p>}

          <div className="mt-10 grid gap-6 sm:grid-cols-2">
            {plans.map((plan) => {
              const isCurrentPlan = isSubscribed && user.billing_interval === plan.id
              return (
                <div
                  key={plan.id}
                  className={`flex flex-col rounded-2xl border bg-white p-6 shadow-sm ${
                    isCurrentPlan ? 'border-ember ring-1 ring-ember' : 'border-line'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="font-display text-lg font-semibold text-ink">{plan.name}</h2>
                    {isCurrentPlan && (
                      <span className="rounded-full bg-mist px-3 py-1 text-xs font-semibold text-ember">
                        Current plan
                      </span>
                    )}
                  </div>
                  <p className="mt-3">
                    <span className="font-display text-3xl font-semibold flame-text-gradient">
                      {plan.price}
                    </span>
                    <span className="text-sm text-ink-soft"> {plan.cadence}</span>
                  </p>
                  <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-soft">
                    {isCurrentPlan
                      ? user.current_period_end
                        ? `Renews ${new Date(user.current_period_end).toLocaleDateString()}.`
                        : "You're all set — you have full access."
                      : plan.blurb}
                  </p>
                  {isCurrentPlan ? (
                    <button
                      type="button"
                      onClick={handleManageBilling}
                      disabled={portalLoading}
                      className="mt-6 rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
                    >
                      {portalLoading ? 'Opening…' : 'Manage subscription'}
                    </button>
                  ) : isSubscribed ? (
                    <button
                      type="button"
                      onClick={handleManageBilling}
                      disabled={portalLoading}
                      className="mt-6 rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
                    >
                      {portalLoading ? 'Opening…' : 'Switch in subscription settings'}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleChoose(plan.id)}
                      disabled={loadingPlan === plan.id}
                      className="mt-6 rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03] disabled:opacity-60"
                    >
                      {loadingPlan === plan.id
                        ? 'Redirecting…'
                        : user
                          ? `Choose ${plan.name.toLowerCase()}`
                          : 'Log in to subscribe'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>

          <p className="mt-6 text-sm font-medium text-ink-soft">Cancel anytime.</p>

          <div className="mt-12 space-y-4 border-t border-line pt-8 text-sm leading-relaxed text-ink-soft">
            <h2 className="font-display text-base font-semibold text-ink">
              Here's what we won't be doing
            </h2>
            <p>
              <strong className="font-semibold text-ink">Giving it away for free, or with a
              longer trial.</strong> This tool has value, and while $3.99 or $9.99 won't break the
              bank, paying for it means you'll actually use it. That's called incentive. You're
              welcome.
            </p>
            <p>
              <strong className="font-semibold text-ink">An annual plan.</strong> Dude — if you're
              still looking for a job using this tool correctly in a year, or frankly in six months,
              then neither of us is doing as good a job as we should.
            </p>
            <p>
              Still worried it's not worth trying for $3.99 a week? Then you really need to stick with
              the free tools, and join that crowd.
            </p>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}