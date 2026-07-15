import { Link, useNavigate } from 'react-router-dom'
import logo from '../assets/logo.jpg'
import { useAuth } from '../lib/auth'

const links = [
  { label: 'What is this?', href: '#what-is-this' },
  { label: 'Pricing', href: '#pricing' },
  { label: 'About us', href: '#about' },
]

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/')
  }

  return (
    <header className="w-full">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="SmarterJobHunt" className="h-10 w-10" />
          <span className="font-display text-lg font-semibold tracking-tight text-ink">
            SmarterJobHunt
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {links.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="text-sm font-medium text-ink-soft transition-colors hover:text-ink"
            >
              {link.label}
            </a>
          ))}
          {user ? (
            <div className="flex items-center gap-4">
              <span className="text-sm text-ink-soft">{user.email}</span>
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
