// Renders a count as a row of flip-clock digit tiles (see
// public/images/flip-clock/{0-9}.png) instead of plain text -- used by the
// landing page's "Current Company Count" / "Current Job Count" stats.
//
// `value` is zero-padded to `digits` places so the tile count never shifts
// as the number animates up (see useCountUp), matching the old
// font-mono padCount() behavior it replaces.

const DIGIT_SRC = Array.from({ length: 10 }, (_, i) => `/images/flip-clock/${i}.png`)

export default function FlipCounter({ value, digits = 5, className = '' }) {
  const padded = String(Math.max(0, Math.trunc(value || 0))).padStart(digits, '0')

  return (
    <span className={`inline-flex items-center gap-[2px] align-middle ${className}`}>
      {padded.split('').map((digit, i) => (
        <img
          key={i}
          src={DIGIT_SRC[Number(digit)]}
          alt={digit}
          draggable={false}
          className="h-6 w-auto select-none drop-shadow-sm md:h-7"
        />
      ))}
    </span>
  )
}
