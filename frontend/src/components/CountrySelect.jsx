import { useEffect, useState } from 'react'
import { fetchGeo } from '../lib/geo'

// Country dropdown for the sign-up form (and the checkout country prompt).
// Pre-fills from the visitor's IP once, unless the user already picked one.
// The backend trusts the IP's country for billing when it isn't a VPN, and
// falls back to this choice when it is -- see backend/ip_country.py.
export default function CountrySelect({ id = 'country', value, onChange, required = true }) {
  const [countries, setCountries] = useState([])

  useEffect(() => {
    let active = true
    fetchGeo().then((geo) => {
      if (!active) return
      setCountries(geo.countries || [])
      if (!value && geo.suggested_country) onChange(geo.suggested_country)
    })
    return () => {
      active = false
    }
    // Only on mount: never overwrite a choice the user has made.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <select
      id={id}
      required={required}
      value={value || ''}
      onChange={(event) => onChange(event.target.value)}
      className="mt-2 w-full rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink focus:border-ember focus:outline-none"
    >
      <option value="" disabled>
        {countries.length ? 'Select your country' : 'Loading countries…'}
      </option>
      {countries.map((country) => (
        <option key={country.code} value={country.code}>
          {country.name}
        </option>
      ))}
    </select>
  )
}
