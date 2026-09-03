import { Link, useLocation, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.jpg'
import { useAuth } from '../lib/auth'

const links = [
  { label: 'What is this?', to: '/what-is-this' },
  { label: 'Pricing', to: '/pricing' },
  { label: 'FAQ', to: '/faq' },
  { label: 'About us', to: '/about' },
]

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  function handleLogout() {
    logout()
    navigate('/')
  }

  // Brand click is context-sensitive: from Job Listings it goes back to the
  // Landing page; from anywhere else (including Profile) it goes to Job
  // Listings, same as the old fixed '/dashboard' behavior.
  const brandTo = location.pathname === '/dashboard' ? '/' : '/dashboard'

  return (
    <header className="w-full">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Link to={brandTo} className="flex items-center gap-3">
          <img src={logo} alt="JobBeggar" className="h-10 w-10" />
          <span className="font-display text-lg font-semibold tracking-tight text-ink">
            JobBeggar
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {links.map((link) => (
            <Link
              key={link.label}
              to={link.to}
              className="text-sm font-medium text-ink-soft transition-colors hover:text-ink"
            >
              {link.label}
            </Link>
          ))}
          {user ? (
            <div className="flex items-center gap-4">
              <Link
                to="/profile"
                title={user.email}
                aria-label={user.email}
                className="flame-gradient flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold uppercase text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.05]"
              >
                {user.email.slice(0, 2)}
              </Link>
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-full border border-line px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-mist"
              >
                Log out
              </button>
            </div>
          ) : (
            <Link
              to="/login"
              className="rounded-full flame-gradient px-5 py-2.5 text-sm font-semibold text-white shadow-sm shadow-ember/20 transition-transform hover:scale-[1.03]"
            >
              Create account / Log in
            </Link>
          )}
        </nav>
      </div>
    </header>
  )
}