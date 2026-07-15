export default function PillRadioGroup({ name, options, value, onChange }) {
  return (
    <div className="flex flex-col gap-1.5" role="radiogroup" aria-label={name}>
      {options.map((option) => {
        const selected = value === option.value
        return (
          <label
            key={option.value}
            className="flex items-center gap-2 text-sm text-ink cursor-pointer"
          >
            <input
              type="radio"
              name={name}
              checked={selected}
              onChange={() => onChange(option.value)}
              className="h-4 w-4 accent-moss cursor-pointer"
            />
            {option.label}
          </label>
        )
      })}
    </div>
  )
}