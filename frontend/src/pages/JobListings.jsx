import { useEffect, useState } from 'react'
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

  return (
    <div className="min-h-screen flame-gradient">
      <div className="mx-auto min-h-screen max-w-6xl bg-paper shadow-2xl shadow-ink/10">
        <Navbar />

        <main className="px-6 pb-16">
          <div className="mx-auto max-w-6xl">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-6">
              <h1 className="font-display text-2xl font-semibold text-ink">
                Your job listings
              </h1>
              <p className="text-sm text-ink-soft">
                {loading
                  ? 'Loading…'
                  : `${totalCount} match${totalCount === 1 ? '' : 'es'} for your current filters`}
              </p>
            </div>

            <div className="mt-8 flex flex-col gap-8 md:flex-row">
              <FilterSidebar
                filters={filters}
                onFilterChange={setFilters}
                onUpdateListings={() => setAppliedFilters(filters)}
                savedSearches={savedSearches}
                onSaveSearch={handleSaveSearch}
                onDeleteSearch={handleDeleteSearch}
                loggedIn={Boolean(user)}
              />

              <div className="flex-1 space-y-4">
                {error ? (
                  <div className="rounded-2xl border border-dashed border-line p-10 text-center text-sm text-ink-soft">
                    Couldn't load job listings ({error}). Check that the backend is running and
                    reachable.
                  </div>
                ) : !loading && jobs.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-line p-10 text-center text-sm text-ink-soft">
                    No roles match those filters yet. Try widening your search or checking
                    back after the next scrape.
                  </div>
                ) : (
                  jobs.map((job) => (
                    <JobCard
                      key={job.id}
                      job={job}
                      status={getStatus(job.id)}
                      onStatusChange={(status) => setStatus(job.id, status)}
                    />
                  ))
                )}
              </div>
            </div>
          </div>
        </main>

        <Footer />
      </div>
    </div>
  )
}