import { useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import FilterSidebar from '../components/FilterSidebar'
import JobCard from '../components/JobCard'
import ActiveFiltersBar from '../components/ActiveFiltersBar'
import DefaultFiltersModal from '../components/DefaultFiltersModal'
import SubscribeModal from '../components/SubscribeModal'
import { fetchJobs, fetchSavedSearches, createSavedSearch, deleteSavedSearch, setJobStatus, fetchTitleVariants } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function JobListings() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user, updateDefaultFilters } = useAuth()
  const sidebarRef = useRef(null)
  const appliedUserDefaultsRef = useRef(false)
  const [filters, setFilters] = useState({
    title: searchParams.get('title') || '',
    variants: 10,
    postedDays: '',
  })
  const [appliedFilters, setAppliedFilters] = useState(filters)
  const [savedSearches, setSavedSearches] = useState([])
  const [statusByJob, setStatusByJob] = useState({})
  const [jobs, setJobs] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showDefaultsModal, setShowDefaultsModal] = useState(false)
  const [showSubscribeModal, setShowSubscribeModal] = useState(false)
  const canApply = user?.plan === 'pro'
  const [savingDefaults, setSavingDefaults] = useState(false)
  const [titleVariants, setTitleVariants] = useState([])
  const [titleVariantsLoading, setTitleVariantsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function run() {
      let variants = []
      if (appliedFilters.title) {
        setTitleVariantsLoading(true)
        try {
          variants = await fetchTitleVariants(appliedFilters.title)
        } catch {
          variants = []
        } finally {
          if (!cancelled) setTitleVariantsLoading(false)
        }
      }
      if (cancelled) return
      setTitleVariants(variants)

      try {
        const { jobs: results, totalCount: total } = await fetchJobs({
          ...appliedFilters,
          variantTitles: variants.slice(0, appliedFilters.variants),
        })
        if (cancelled) return
        setJobs(results)
        setTotalCount(total)
        setStatusByJob((prev) => {
          const next = { ...prev }
          for (const job of results) {
            if (job.status) next[job.id] = { value: job.status, reason: job.reasonRejected || '' }
          }
          return next
        })
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    run()

    return () => {
      cancelled = true
    }
  }, [appliedFilters])

  useEffect(() => {
    if (!user) {
      setSavedSearches([])
      return
    }
    fetchSavedSearches()
      .then(setSavedSearches)
      .catch(() => setSavedSearches([]))
  }, [user])

  useEffect(() => {
    if (!user || appliedUserDefaultsRef.current) return
    appliedUserDefaultsRef.current = true

    // If the user arrived here with a title from the landing page search
    // (or any other explicit ?title= link), that takes priority — don't
    // let saved account defaults overwrite it.
    if (searchParams.get('title')) return

    if (user.has_set_default_filters) {
      const seeded = {
        title: user.default_job_title || '',
        variants: user.default_variants || 10,
        postedDays: user.default_posted_within_days || '',
      }
      setFilters(seeded)
      setAppliedFilters(seeded)
    } else {
      setShowDefaultsModal(true)
    }
  }, [user, searchParams])

  function handleSaveDefaults(newFilters) {
    setSavingDefaults(true)
    updateDefaultFilters(newFilters)
      .then(() => {
        setFilters(newFilters)
        setAppliedFilters(newFilters)
        setShowDefaultsModal(false)
      })
      .catch((err) => setError(err.message))
      .finally(() => setSavingDefaults(false))
  }

  function handleSkipDefaults() {
    setSavingDefaults(true)
    updateDefaultFilters({ title: '', variants: 10, postedDays: '' })
      .then(() => setShowDefaultsModal(false))
      .catch((err) => setError(err.message))
      .finally(() => setSavingDefaults(false))
  }

  function handleActiveFiltersChange(newFilters) {
    setFilters(newFilters)
    setAppliedFilters(newFilters)
  }

  function getStatus(jobId) {
    return statusByJob[jobId] || { value: null, reason: '' }
  }

  function setStatus(jobId, status) {
    if (!user) {
      navigate('/login')
      return
    }
    setStatusByJob((prev) => ({ ...prev, [jobId]: status }))
    if (status.value) {
      setJobStatus(jobId, status.value, status.reason).catch((err) => setError(err.message))
    }
  }

  function handleSaveSearch(name) {
    if (!user) {
      navigate('/login')
      return
    }
    createSavedSearch({
      name,
      jobTitle: filters.title,
      variants: filters.variants,
      postedWithinDays: filters.postedDays || null,
    })
      .then((saved) => setSavedSearches((prev) => [saved, ...prev]))
      .catch((err) => setError(err.message))
  }

  function handleDeleteSearch(id) {
    deleteSavedSearch(id)
      .then(() => setSavedSearches((prev) => prev.filter((search) => search.id !== id)))
      .catch((err) => setError(err.message))
  }

  function scrollToFilters() {
    sidebarRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="min-h-screen bg-paper">
      <Navbar />

      {showDefaultsModal && (
        <DefaultFiltersModal
          onSave={handleSaveDefaults}
          onSkip={handleSkipDefaults}
          saving={savingDefaults}
        />
      )}

      {showSubscribeModal && <SubscribeModal onClose={() => setShowSubscribeModal(false)} />}

      <main className="mx-auto max-w-6xl px-6 pb-16 pt-8">
        <div className="border border-line">
          <div className="border-b border-line py-4 text-center">
            <h1 className="text-xl font-semibold text-ink">Your Job Listings</h1>
            <button
              type="button"
              onClick={scrollToFilters}
              className="mt-1 text-sm text-ember underline decoration-line underline-offset-2 hover:text-flame md:hidden"
            >
              Search Criteria
            </button>
            {!loading && (
              <p className="mt-1 text-xs text-ink-soft">
                {totalCount} match{totalCount === 1 ? '' : 'es'} for your current filters
              </p>
            )}
          </div>

          <ActiveFiltersBar
            filters={appliedFilters}
            onChange={handleActiveFiltersChange}
            titleVariants={titleVariants}
            titleVariantsLoading={titleVariantsLoading}
          />

          <div className="flex flex-col gap-6 p-6 md:flex-row">
            <div ref={sidebarRef}>
              <FilterSidebar
                filters={filters}
                onFilterChange={setFilters}
                onUpdateListings={() => setAppliedFilters(filters)}
                savedSearches={savedSearches}
                onSaveSearch={handleSaveSearch}
                onDeleteSearch={handleDeleteSearch}
                loggedIn={Boolean(user)}
              />
            </div>

            <div className="flex-1">
              {error ? (
                <div className="border border-dashed border-line p-10 text-center text-sm text-ink-soft">
                  Couldn't load job listings ({error}). Check that the backend is running and
                  reachable.
                </div>
              ) : !loading && jobs.length === 0 ? (
                <div className="border border-dashed border-line p-10 text-center text-sm text-ink-soft">
                  No roles match those filters yet. Try widening your search or checking
                  back after the next scrape.
                </div>
              ) : (
                <div className="border border-line divide-y divide-line">
                  {jobs.map((job, index) => (
                    <JobCard
                      key={job.id}
                      job={job}
                      status={getStatus(job.id)}
                      onStatusChange={(status) => setStatus(job.id, status)}
                      shaded={index % 2 === 1}
                      canApply={canApply}
                      onRequireSubscription={() => setShowSubscribeModal(true)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}