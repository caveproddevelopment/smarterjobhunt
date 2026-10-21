import logo from '../assets/logo.jpg'
import SEO from '../components/SEO'

// Holding page shown at "/" while the site is being finished. The real
// landing page lives at /home; every other route still works by direct URL.
export default function UnderConstruction() {
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-paper px-6 text-center">
      <SEO
        title="JobBeggar - Site Under Construction"
        description="JobBeggar is getting ready. Search company career pages directly and skip the job boards. Check back soon."
        path="/"
      />

      <div
        aria-hidden="true"
        className="flame-gradient pointer-events-none absolute -top-40 left-1/2 h-80 w-[36rem] -translate-x-1/2 rounded-full opacity-15 blur-3xl"
      />

      <img src={logo} alt="JobBeggar" className="h-16 w-16 rounded-xl shadow-sm" />
      <p className="mt-4 font-display text-xl font-semibold tracking-tight text-ink">JobBeggar</p>

      <span className="mt-10 inline-flex items-center gap-2 rounded-full border border-line bg-mist px-4 py-1.5 font-mono text-xs font-medium uppercase tracking-wider text-ink-soft">
        <span className="h-2 w-2 animate-pulse rounded-full bg-flame" />
        Work in progress
      </span>

      <h1 className="mt-6 max-w-2xl font-display text-4xl font-bold tracking-tight text-ink sm:text-6xl">
        Site <span className="flame-text-gradient">under construction</span>
      </h1>

      <p className="mt-5 max-w-xl text-base leading-relaxed text-ink-soft sm:text-lg">
        We're building a better way to find your next job, straight from the career pages of
        companies you'd actually work for. Check back soon.
      </p>

      <p className="absolute bottom-6 text-xs text-ink-soft">
        © {new Date().getFullYear()} JobBeggar
      </p>
    </main>
  )
}
