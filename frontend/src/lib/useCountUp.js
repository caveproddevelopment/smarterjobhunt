import { useEffect, useRef, useState } from 'react'

// Animates a number counting up from 0 to `target` on an eased
// requestAnimationFrame loop (not a linear interval tick), re-running
// whenever `target` changes -- e.g. once the real count arrives from the
// API and replaces the initial 0. Returns the in-progress integer value to
// render on each frame.
export function useCountUp(target, durationMs = 1500) {
  const [value, setValue] = useState(0)
  const frameRef = useRef(null)

  useEffect(() => {
    if (!target) {
      setValue(0)
      return
    }

    const startTime = performance.now()

    function tick(now) {
      const progress = Math.min((now - startTime) / durationMs, 1)
      const eased = 1 - Math.pow(1 - progress, 3) // easeOutCubic
      setValue(Math.round(target * eased))
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(tick)
      }
    }

    frameRef.current = requestAnimationFrame(tick)
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current)
    }
  }, [target, durationMs])

  return value
}
