import { useState } from 'react'
import CountrySelect from './CountrySelect'

// Shown by AuthProvider.startCheckout() when the backend can't tell where
// the user is (no country on file and their IP is a VPN/proxy -- typically
// a Google sign-up), because the country decides Stripe vs Razorpay.
export default function CountryPromptModal({ onSubmit, onCancel }) {
  const [country, setCountry] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (country) onSubmit(country)
        }}
        className="w-full max-w-md border border-line bg-paper p-6 shadow-xl"
      >
        <h2 className="font-display text-lg font-semibold text-ink">Where are you based?</h2>
        <p className="mt-1 text-sm text-ink-soft">
          We use your country to pick the right payment method for your free trial.
        </p>
        <label htmlFor="checkout-country" className="mt-4 block text-sm font-medium text-ink">
          Country
        </label>
        <CountrySelect id="checkout-country" value={country} onChange={setCountry} />
        <button
          type="submit"
          disabled={!country}
          className="mt-5 w-full rounded-full flame-gradient py-2.5 text-sm font-semibold text-white transition-transform hover:scale-[1.02] disabled:opacity-60"
        >
          Continue
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="mt-3 w-full rounded-full border border-line py-2.5 text-sm font-medium text-ink hover:bg-mist"
        >
          Cancel
        </button>
      </form>
    </div>
  )
}
