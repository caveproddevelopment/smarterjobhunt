import { useState } from 'react'

// Drop-in replacement for <input type="password" />, with a show/hide
// toggle on the right side of the field. Any extra props (id, required,
// minLength, placeholder, autoComplete, etc.) are passed straight through
// to the underlying <input>.
export default function PasswordInput({ value, onChange, className = '', ...rest }) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="relative">
      <input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={onChange}
        className={`w-full rounded-lg border border-line px-3 py-2 pr-10 text-sm text-ink focus:border-ember focus:outline-none ${className}`}
        {...rest}
      />
      <button
        type="button"
        onClick={() => setVisible((prev) => !prev)}
        tabIndex={-1}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-ink-soft transition-colors hover:text-ink"
      >
        {visible ? (
          // Eye-off icon
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4.5 w-4.5"
            width="18"
            height="18"
          >
            <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
            <path d="M10.73 5.08A10.4 10.4 0 0 1 12 5c5 0 9 4.5 10 7-.46 1.15-1.18 2.36-2.13 3.44" />
            <path d="M6.61 6.61C4.36 8.06 2.7 10.13 2 12c1 2.5 5 7 10 7a9.9 9.9 0 0 0 4.24-.94" />
            <path d="M2 2l20 20" />
          </svg>
        ) : (
          // Eye icon
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-4.5 w-4.5"
            width="18"
            height="18"
          >
            <path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  )
}
