import { useEffect, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import FilterSidebar from '../components/FilterSidebar'
import JobCard from '../components/JobCard'
import ActiveFiltersBar from '../components/ActiveFiltersBar'
import DefaultFiltersModal from '../components/DefaultFiltersModal'
import SubscribeModal from '../components/SubscribeModal'
import {
  fetchJobs,
  fetchSavedSearches,
  createSavedSearch,
  deleteSavedSearch,
  setJobStatus,
  fetchTitleVariants,
  fetchVariantCounts,
} from '../lib/api'
import { useAuth } from '../lib/auth'

function buildBookmarkName(f) {
  const title = (f.title || '').trim()
  const days = f.postedDays ? String(f.postedDays).trim() : ''
  const label = title || 'All jobs'
  return days ? `${label} · last ${days} day${days === '1' ? '' : 's'}` : label
}

export default function JobListings() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user, updateDefaultFilters } = useAuth()
  const sidebarRef = useRef(null)
  const appliedUserDefaultsRef = useRef(false)
  const [filters, setFilters] = useState({
    title: searchParams.get('title') || '',
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
  const [variantCounts, setVariantCounts] = useState({})
  const [variantCountsLoading, setVariantCountsLoading] = useState(false)
  // Which "Also matching" pill (if any) the listing below is currently
  // scoped to. null means the normal combined title+variants view.
  const [selectedVariant, setSelectedVariant] = useState(null)
  // Tracks the title+postedDays combo the current titleVariants/variantCounts
  // were fetched for, so toggling selectedVariant alone doesn't re-trigger
  // those fetches (and flicker the pill numbers) when nothing else changed.
  const variantsKeyRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function run() {
      // Only re-derive titleVariants/variantCounts when the title or
      // posted-days filter actually changed. Toggling selectedVariant alone
      // (clicking a pill / "Return to Full List") reuses what's already
      // loaded instead of re-fetching and flickering the pill numbers.
      const variantsKey = `${appliedFilters.title}|||${appliedFilters.postedDays}`
      const filtersChanged = variantsKeyRef.current !== variantsKey

      let variants = titleVariants
      if (filtersChanged) {
        variants = []
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
        // Clear stale counts from the previous title right away, so a pill
        // never briefly shows a number left over from a different search.
        setVariantCounts({})

        // Per-variant counts drive which "Also matching" pills are
        // clickable. Fetched in the background so a slow count lookup never
        // blocks the job list itself from rendering.
        if (variants.length > 0) {
          setVariantCountsLoading(true)
          fetchVariantCounts(variants, { postedDays: appliedFilters.postedDays })
            .then((counts) => {
              if (!cancelled) setVariantCounts(counts)
            })
            .catch(() => {
              if (!cancelled) setVariantCounts({})
            })
            .finally(() => {
              if (!cancelled) setVariantCountsLoading(false)
            })
        }
        variantsKeyRef.current = variantsKey
      }

      // A selected variant scopes the listing to ONLY that variant's jobs
      // (title left out entirely, no OR'ing with the other variants). With
      // nothing selected, it's the normal combined title + all-variants view.
      const jobParams = selectedVariant
        ? { title: '', postedDays: appliedFilters.postedDays, variantTitles: [selectedVariant] }
        : { ...appliedFilters, variantTitles: variants }

      try {
        const { jobs: results, totalCount: total } = await fetchJobs(jobParams)
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
  }, [appliedFilters, selectedVariant])

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
        setSelectedVariant(null)
        setShowDefaultsModal(false)
      })
      .catch((err) => setError(err.message))
      .finally(() => setSavingDefaults(false))
  }

  function handleSkipDefaults() {
    setSavingDefaults(true)
    updateDefaultFilters({ title: '', postedDays: '' })
      .then(() => setShowDefaultsModal(false))
      .catch((err) => setError(err.message))
      .finally(() => setSavingDefaults(false))
  }

  function handleActiveFiltersChange(newFilters) {
    setFilters(newFilters)
    setAppliedFilters(newFilters)
    setSelectedVariant(null)
  }

  function handleUpdateListings() {
    setAppliedFilters(filters)
    setSelectedVariant(null)
  }

  // Clicking a clickable "Also matching" pill scopes the listing to ONLY
  // that variant. Clicking the already-selected pill again is a shortcut
  // back to the full list, same as the header's "Return to Full List".
  function handleSelectVariant(variant) {
    const count = variantCounts[variant]
    if (!count) return
    setSelectedVariant((prev) => (prev === variant ? null : variant))
  }

  function handleReturnToFullList() {
    setSelectedVariant(null)
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

  function handleDeleteSearch(id) {
    deleteSavedSearch(id)
      .then(() => setSavedSearches((prev) => prev.filter((search) => search.id !== id)))
      .catch((err) => setError(err.message))
  }

  // A "bookmark" matches the *entire* current search (title + posted-days),
  // the same way a browser bookmark points at one specific page/state —
  // not just the title. When a variant pill is selected, the current view
  // is scoped to that variant's title, so the bookmark should track (and be
  // saved under) the variant title instead of the original search title.
  const bookmarkTitle = selectedVariant || appliedFilters.title || ''
  const bookmarkedSearch = savedSearches.find((search) => {
    const sameTitle = (search.job_title || '') === bookmarkTitle
    const sameDays = String(search.posted_within_days || '') === String(appliedFilters.postedDays || '')
    return sameTitle && sameDays
  })

  function handleToggleBookmark() {
    if (!user) {
      navigate('/login')
      return
    }
    if (bookmarkedSearch) {
      handleDeleteSearch(bookmarkedSearch.id)
      return
    }
    createSavedSearch({
      name: buildBookmarkName({ ...appliedFilters, title: bookmarkTitle }),
      jobTitle: bookmarkTitle,
      postedWithinDays: appliedFilters.postedDays || null,
    })
      .then((saved) => setSavedSearches((prev) => [saved, ...prev]))
      .catch((err) => setError(err.message))
  }

  // Clicking a bookmarked search in the sidebar jumps straight to those
  // results, the way clicking a browser bookmark takes you straight to
  // the page instead of just filling in an address bar.
  function handleApplySearch(search) {
    const applied = {
      title: search.job_title || '',
      postedDays: search.posted_within_days != null ? String(search.posted_within_days) : '',
    }
    setFilters(applied)
    setAppliedFilters(applied)
    setSelectedVariant(null)
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
            {selectedVariant ? (
              <div className="relative px-4 sm:px-14">
                <button
                  type="button"
                  onClick={handleReturnToFullList}
                  className="absolute left-0 top-1/2 flex -translate-y-1/2 items-center gap-1.5 text-sm font-medium text-ember hover:text-flame"
                >
                  <span aria-hidden="true">←</span>
                  Return to Full List
                </button>
                <h1 className="text-xl font-semibold text-ink">
                  Current View: <span className="text-ember">{selectedVariant}</span>
                </h1>
              </div>
            ) : (
              <>
                <h1 className="text-xl font-semibold text-ink">Your Job Listings</h1>
                <button
                  type="button"
                  onClick={scrollToFilters}
                  className="mt-1 text-sm text-ember underline decoration-line underline-offset-2 hover:text-flame md:hidden"
                >
                  Search Criteria
                </button>
              </>
            )}
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
            variantCounts={variantCounts}
            variantCountsLoading={variantCountsLoading}
            selectedVariant={selectedVariant}
            onSelectVariant={handleSelectVariant}
            bookmarked={Boolean(bookmarkedSearch)}
            onToggleBookmark={handleToggleBookmark}
          />

          <div className="flex flex-col gap-6 p-6 md:flex-row">
            <div ref={sidebarRef}>
              <FilterSidebar
                filters={filters}
                onFilterChange={setFilters}
                onUpdateListings={handleUpdateListings}
                savedSearches={savedSearches}
                onApplySearch={handleApplySearch}
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