import { POSTED_DAYS_OPTIONS } from '../lib/postedDays'

// Segmented 1 week / 2 weeks / All control for "Posted in the last".
export default function PostedDaysPicker({ id, value, onChange }) {
  return (
    <div id={id} role="radiogroup" aria-label="Posted in the last" className="flex border border-line">
      {POSTED_DAYS_OPTIONS.map((option, index) => {
        const selected = (value || '') === option.value
        return (
          <button
            key={option.label}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className={`flex-1 whitespace-nowrap px-2 py-1.5 text-xs font-medium transition-colors ${
              index > 0 ? 'border-l border-line' : ''
            } ${selected ? 'bg-ink text-paper' : 'bg-paper text-ink hover:bg-mist'}`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
