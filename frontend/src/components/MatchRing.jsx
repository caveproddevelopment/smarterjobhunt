export default function MatchRing({ percent = 0, size = 56 }) {
  const stroke = size * 0.11
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - percent / 100)
  const gradientId = `ring-gradient-${size}-${percent}`

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--color-ember)" />
            <stop offset="55%" stopColor="var(--color-flame)" />
            <stop offset="100%" stopColor="var(--color-spark)" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-line)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center font-mono font-semibold text-ink"
        style={{ fontSize: size * 0.26 }}
      >
        {percent}%
      </span>
    </div>
  )
}
