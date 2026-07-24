import { useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import FilterSidebar from '../components/FilterSidebar'
import JobCard from '../components/JobCard'
import { fetchJobs, fetchSavedSearches, createSavedSearch, deleteSavedSearch, setJobStatus } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function JobListings() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const sidebarRef = useRef(null)
  const [filters, setFilters] = useState({
    title: searchParams.get('title') || '',
    variants: 10,
    postedDays: '',
    funding: 'both',
  })
  const [appliedFilters, setAppliedFilters] = useState(filters)
  const [savedSearches, setSavedSearches] = useState([])
  const [statusByJob, setStatusByJob] = useState({})
  const [jobs, setJobs] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchJobs(appliedFilters)
      .then(({ jobs: results, totalCount: total }) => {
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
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

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
      fundingFilter: filters.funding,
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