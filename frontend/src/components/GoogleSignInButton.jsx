import { useEffect, useRef } from 'react'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

// Renders Google's own "Sign in with Google" button via the Google Identity
// Services script (loaded in index.html). No extra npm package needed --
// window.google is set by that script once it finishes loading, which is
// why this polls briefly rather than assuming it's ready on mount.
export default function GoogleSignInButton({ onCredential, disabled }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || disabled) return

    let cancelled = false
    let pollId

    function render() {
      if (cancelled || !containerRef.current || !window.google?.accounts?.id) return

      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: (response) => onCredential(response.credential),
      })

      containerRef.current.innerHTML = ''
      window.google.accounts.id.renderButton(containerRef.current, {
        type: 'standard',
        theme: 'outline',
        size: 'large',
        shape: 'pill',
        text: 'continue_with',
        width: 360,
      })
    }

    if (window.google?.accounts?.id) {
      render()
    } else {
      pollId = setInterval(() => {
        if (window.google?.accounts?.id) {
          clearInterval(pollId)
          render()
        }
      }, 100)
    }

    return () => {
      cancelled = true
      if (pollId) clearInterval(pollId)
    }
  }, [disabled, onCredential])

  if (!GOOGLE_CLIENT_ID) return null

  return <div ref={containerRef} className="flex justify-center" />
}
