import logo from '../assets/logo.jpg'

export default function Footer() {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-6 py-10 text-sm text-ink-soft md:flex-row md:justify-between">
        <div className="flex items-center gap-2">
          <img src={logo} alt="SmarterJobHunt" className="h-6 w-6" />
          <span className="font-display font-medium text-ink">SmarterJobHunt</span>
        </div>
        <p>© {new Date().getFullYear()} SmarterJobHunt. Close the loop on your job search.</p>
      </div>
    </footer>
  )
}
