export default function LoopVisual() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-sm">
      <svg viewBox="0 0 320 320" className="h-full w-full">
        <defs>
          <linearGradient id="loop-outer" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--color-sky)" />
            <stop offset="45%" stopColor="var(--color-moss)" />
            <stop offset="100%" stopColor="var(--color-spark)" />
          </linearGradient>
          <linearGradient id="loop-inner" x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--color-ember)" />
            <stop offset="100%" stopColor="var(--color-spark)" />
          </linearGradient>
        </defs>

        <circle
          cx="160"
          cy="160"
          r="128"
          fill="none"
          stroke="url(#loop-outer)"
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray="700 804"
          transform="rotate(-100 160 160)"
        />
        <circle
          cx="160"
          cy="160"
          r="92"
          fill="none"
          stroke="url(#loop-inner)"
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray="430 578"
          transform="rotate(140 160 160)"
        />

        <g className="motion-safe:animate-[spin_16s_linear_infinite]" style={{ transformOrigin: '160px 160px' }}>
          <circle cx="160" cy="32" r="7" fill="var(--color-flame)" />
        </g>

        <text
          x="160"
          y="152"
          textAnchor="middle"
          className="font-display"
          fontSize="30"
          fontWeight="700"
          fill="var(--color-ink)"
        >
          92%
        </text>
        <text
          x="160"
          y="176"
          textAnchor="middle"
          className="font-mono"
          fontSize="12"
          fill="var(--color-ink-soft)"
        >
          match, avg. top pick
        </text>
      </svg>
    </div>
  )
}
