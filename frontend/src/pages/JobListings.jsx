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
  fetchCompanyTypeCounts,
  fetchVariantCounts,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { COMPANY_TYPE_LABELS, DEFAULT_COMPANY_TYPE } from '../lib/companyTypes'

// Describes a saved-search row (or the page's current scoped view, in the
// same shape) as a human name. Distinct per view_type since each one means
// something different to look at later, not just "a title search".
//
// For 'search'/'variant' views, the Company Database scope is folded into
// the name too -- e.g. "product manager · Funded Startups" vs "product
// manager · Fortune 500" -- so the same title bookmarked under two
// different databases gets two distinct, tellable-apart entries in the
// sidebar instead of two identically-named rows.
function buildBookmarkName(view) {
  const days = view.days ? String(view.days) : ''
  const suffix = days ? ` · last ${days} day${days === '1' ? '' : 's'}` : ''
  if (view.viewType === 'status') {
    if (view.statusFilter === 'applied') return 'Applied Jobs'
    if (view.statusFilter === 'rejected') return 'Rejected Jobs'
    return 'Neither Jobs'
  }
  if (view.viewType === 'company') {
    return `All jobs at ${view.companyName}`
  }
  // Handle multiple company types
  const companyTypeLabels = (view.companyTypes || []).map((type) => COMPANY_TYPE_LABELS[type])
  const dbLabel = companyTypeLabels.length > 0 ? ` · ${companyTypeLabels.join(', ')}` : ''
  const remoteLabel = view.remoteOnly ? ' · Remote' : ''
  if (view.viewType === 'variant') {
    return `${view.variantTitle}${suffix}${dbLabel}${remoteLabel}`
  }
  return `${(view.title || '').trim() || 'All jobs'}${suffix}${dbLabel}${remoteLabel}`
}

export default function JobListings() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user, updateDefaultFilters } = useAuth()
  const sidebarRef = useRef(null)
  const appliedUserDefaultsRef = useRef(false)
  // A landing-page badge links here as e.g. ?company_type=fortune500 --
  // only honor it when it's one of the real, known databases, so a
  // malformed/unknown value quietly falls back to the default instead of
  // producing a broken-looking filter state.
  const companyTypeParam = searchParams.get('company_type')
  const linkedCompanyType =
    companyTypeParam && COMPANY_TYPE_LABELS[companyTypeParam] ? companyTypeParam : null

  const [filters, setFilters] = useState({
    title: searchParams.get('title') || '',
    postedDays: '',
    companyTypes: linkedCompanyType ? [linkedCompanyType] : [DEFAULT_COMPANY_TYPE],
    remoteOnly: false,
  })
  const [appliedFilters, setAppliedFilters] = useState(filters)
  const [savedSearches, setSavedSearches] = useState([])
  const [statusByJob, setStatusByJob] = useState({})
  const [jobs, setJobs] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [bookmarkError, setBookmarkError] = useState(null)
  const [showDefaultsModal, setShowDefaultsModal] = useState(false)
  const [showSubscribeModal, setShowSubscribeModal] = useState(false)
  // Pro subscribers always have access; new signups also get it for their
  // first 24 hours (trial_active, computed server-side from created_at --
  // see USER_FIELDS in routes/auth.py). Automatically turns off once the
  // window passes, no separate expiry logic needed here.
  const canApply = user?.plan === 'pro' || user?.trial_active
  const [savingDefaults, setSavingDefaults] = useState(false)
  const [titleVariants, setTitleVariants] = useState([])
  const [titleVariantsLoading, setTitleVariantsLoading] = useState(false)
  // Whether the "See Variants" pill panel in ActiveFiltersBar is expanded.
  const [showVariants, setShowVariants] = useState(false)
  // job_count per variant title -- { "Product Owner": 4, ... } -- fetched
  // lazily the first time the panel is opened for a given title/filters
  // combo, not preloaded on every keystroke.
  const [variantCounts, setVariantCounts] = useState({})
  const [variantCountsLoading, setVariantCountsLoading] = useState(false)
  // The title|||postedDays|||companyTypes combo variantCounts was last
  // fetched for, so re-opening the panel without anything else changing
  // reuses what's already loaded instead of re-fetching.
  const variantCountsKeyRef = useRef(null)
  // Total active jobs in each of the three Company Database options --
  // { funded, fortune500, indianmajor, all } -- unfiltered (not scoped to title,
  // postedDays, or anything else), fetched once on mount.
  const [companyTypeCounts, setCompanyTypeCounts] = useState({})
  const [companyTypeCountsLoading, setCompanyTypeCountsLoading] = useState(false)
  // Which title-variant view (if any) the listing below is currently scoped
  // to -- set via a "See Variants" pill (handleSelectVariant) or restored
  // from a saved bookmark (handleApplySearch). null means the normal
  // combined title+variants view.
  const [selectedVariant, setSelectedVariant] = useState(null)
  // Set when "See them all" is clicked on a job card — scopes the listing
  // to every job at that one company, ignoring title/variant/postedDays
  // filters entirely. Mutually exclusive with selectedVariant.
  const [selectedCompany, setSelectedCompany] = useState(null)
  // Set from the sidebar's "Track Applications" radios (applied / rejected
  // / tracked = both). Scopes the listing to the user's marked jobs across
  // ALL searches, ignoring every other filter. Mutually exclusive with
  // selectedVariant and selectedCompany.
  const [selectedStatus, setSelectedStatus] = useState(null)
  // Tracks the title+postedDays combo the current titleVariants were
  // fetched for, so toggling selectedVariant alone doesn't re-trigger that
  // fetch when nothing else actually changed.
  const variantsKeyRef = useRef(null)
  // job.id -> DOM node for whichever job cards are currently rendered.
  // Populated via a callback ref on each card's wrapper below; used by
  // handleJumpToTitleMatch to scroll a specific card into view.
  const jobCardRefs = useRef({})
  // Briefly highlighted after "Jump to the best-matching job" so the
  // person can actually spot which card it landed on.
  const [highlightedJobId, setHighlightedJobId] = useState(null)
  const highlightTimeoutRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setBookmarkError(null)

    async function run() {
      // Only re-fetch titleVariants when the title or posted-days filter
      // actually changed. Toggling selectedVariant alone (e.g. "Return to
      // Full List") reuses what's already loaded instead of re-fetching.
      const variantsKey = `${appliedFilters.title}|||${appliedFilters.postedDays}|||${(appliedFilters.companyTypes || []).join(',')}`
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
        variantsKeyRef.current = variantsKey
      }

      // selectedStatus (Track Applications) takes priority over everything:
      // it's the user's marked-job history, not a search, so it ignores
      // title/variant/company/postedDays/companyTypes entirely. Next,
      // selectedCompany means every job at that company, full stop. Then a
      // selected variant scopes to ONLY that variant's jobs (title left out
      // entirely, no OR'ing with the other variants). With nothing
      // selected, it's the normal combined title + all-variants view.
      const jobParams = selectedStatus
        ? { title: '', postedDays: '', companyTypes: [], remoteOnly: false, status: selectedStatus }
        : selectedCompany
          ? { title: '', postedDays: '', companyTypes: [], remoteOnly: false, companyId: selectedCompany.id }
          : selectedVariant
            ? {
                title: '',
                postedDays: appliedFilters.postedDays,
                companyTypes: appliedFilters.companyTypes,
                remoteOnly: appliedFilters.remoteOnly,
                variantTitles: [selectedVariant],
              }
            : { ...appliedFilters, variantTitles: variants }

      try {
        const { jobs: results, totalCount: total } = await fetchJobs(jobParams)
        if (cancelled) return
        jobCardRefs.current = {}
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
  }, [appliedFilters, selectedVariant, selectedCompany, selectedStatus])

  // Fetches per-variant job counts for the "See Variants" popup, lazily --
  // only once it's actually open, and only re-fetching when the title,
  // posted-days, or Company Database scope it was fetched for no longer
  // matches what's currently applied. Includes the original searched title
  // itself alongside the 15 variants, so the popup can show a count on
  // that pill too, not just the variants.
  useEffect(() => {
    if (!showVariants || titleVariants.length === 0) return
    const key = `${appliedFilters.title}|||${appliedFilters.postedDays}|||${(appliedFilters.companyTypes || []).join(',')}`
    if (variantCountsKeyRef.current === key) return

    let cancelled = false
    setVariantCountsLoading(true)
    const titlesToCount = appliedFilters.title ? [appliedFilters.title, ...titleVariants] : titleVariants
    fetchVariantCounts(titlesToCount, {
      postedDays: appliedFilters.postedDays,
      companyTypes: appliedFilters.companyTypes,
    })
      .then((counts) => {
        if (cancelled) return
        setVariantCounts(counts)
        variantCountsKeyRef.current = key
      })
      .catch(() => {
        if (!cancelled) setVariantCounts({})
      })
      .finally(() => {
        if (!cancelled) setVariantCountsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [showVariants, titleVariants, appliedFilters.title, appliedFilters.postedDays, appliedFilters.companyTypes])

  // Total jobs per company database, unfiltered -- fetched once on mount
  // (not tied to title/postedDays/companyType at all), since it's meant to
  // show the overall size of each database, not a per-search count.
  useEffect(() => {
    let cancelled = false
    setCompanyTypeCountsLoading(true)
    fetchCompanyTypeCounts()
      .then((counts) => {
        if (!cancelled) setCompanyTypeCounts(counts)
      })
      .catch(() => {
        if (!cancelled) setCompanyTypeCounts({})
      })
      .finally(() => {
        if (!cancelled) setCompanyTypeCountsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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

    // If the user arrived here with a title or company database from the
    // landing page (or any other explicit ?title=/?company_type= link),
    // that takes priority — don't let saved account defaults overwrite it.
    if (searchParams.get('title') || linkedCompanyType) return

    if (user.has_set_default_filters) {
      const seeded = {
        title: user.default_job_title || '',
        postedDays: user.default_posted_within_days || '',
        companyTypes: filters.companyTypes || [DEFAULT_COMPANY_TYPE],
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
        setSelectedCompany(null)
        setSelectedStatus(null)
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
    setSelectedCompany(null)
    setSelectedStatus(null)
    setShowVariants(false)
  }

  function handleUpdateListings() {
    setAppliedFilters(filters)
    setSelectedVariant(null)
    setSelectedCompany(null)
    setSelectedStatus(null)
    setShowVariants(false)
  }

  // "See them all" on a job card scopes the listing to every job at that
  // company. { id, name } -- id drives the exact backend filter, name is
  // just for the "Current View: All jobs at X" label. Clicking it again
  // (or from another card at the same company) is a shortcut back to the
  // full list, same as a variant pill.
  function handleSeeCompanyJobs(companyId, companyName) {
    if (!companyId) return
    setSelectedVariant(null)
    setSelectedStatus(null)
    setSelectedCompany((prev) => (prev?.id === companyId ? null : { id: companyId, name: companyName }))
  }

  function handleToggleVariants() {
    setShowVariants((prev) => !prev)
  }

  // Clicking a variant pill in the "See Variants" panel scopes the listing
  // to ONLY that variant's jobs, same as restoring a variant bookmark.
  // Mutually exclusive with selectedCompany/selectedStatus, same rule as
  // everywhere else a view gets picked.
  function handleSelectVariant(variantTitle) {
    setSelectedCompany(null)
    setSelectedStatus(null)
    setSelectedVariant(variantTitle)
    setShowVariants(false)
  }

  // The sidebar's "Track Applications" radios. Picking one shows the
  // user's marked jobs of that kind, across every search -- not just
  // whatever's in the title box right now.
  function handleSelectStatus(value) {
    setSelectedVariant(null)
    setSelectedCompany(null)
    setSelectedStatus(value)
  }

  // Clicking the "Title" chip's label (not its ×) jumps to whichever job in
  // the current list best matches what was typed, instead of clearing the
  // filter: an exact title match if one exists, otherwise the job with the
  // highest search-match %.
  function handleJumpToTitleMatch() {
    if (!jobs.length) return
    const target = appliedFilters.title.trim().toLowerCase()
    let best = jobs.find((job) => job.title.trim().toLowerCase() === target)
    if (!best) {
      for (const job of jobs) {
        if (typeof job.matchPercent !== 'number') continue
        if (!best || job.matchPercent > best.matchPercent) best = job
      }
    }
    if (!best) return
    const node = jobCardRefs.current[best.id]
    node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setHighlightedJobId(best.id)
    if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current)
    highlightTimeoutRef.current = setTimeout(() => setHighlightedJobId(null), 1800)
  }

  function handleReturnToFullList() {
    setSelectedVariant(null)
    setSelectedCompany(null)
    setSelectedStatus(null)
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

  // A single descriptor for whichever view is currently on screen, in the
  // same shape a saved_searches row comes back in. Drives both which
  // bookmark (if any) is already saved for the current view, and what gets
  // sent to the API when saving a new one — so those two things can never
  // drift out of sync with each other.
  const currentView = selectedStatus
    ? { viewType: 'status', statusFilter: selectedStatus }
    : selectedCompany
      ? { viewType: 'company', companyId: selectedCompany.id, companyName: selectedCompany.name }
      : selectedVariant
        ? {
            viewType: 'variant',
            variantTitle: selectedVariant,
            title: appliedFilters.title,
            days: appliedFilters.postedDays,
            companyTypes: appliedFilters.companyTypes,
            remoteOnly: appliedFilters.remoteOnly,
          }
        : {
            viewType: 'search',
            title: appliedFilters.title,
            days: appliedFilters.postedDays,
            companyTypes: appliedFilters.companyTypes,
            remoteOnly: appliedFilters.remoteOnly,
          }

  const bookmarkedSearch = savedSearches.find((search) => {
    if (search.view_type !== currentView.viewType) return false
    if (currentView.viewType === 'status') {
      return search.status_filter === currentView.statusFilter
    }
    if (currentView.viewType === 'company') {
      return search.company_id === currentView.companyId
    }
    const sameDays = String(search.posted_within_days || '') === String(currentView.days || '')
    // Compare company types as arrays - sort both for consistent comparison
    const searchCompanyTypes = (search.company_types || []).sort()
    const currentCompanyTypes = (currentView.companyTypes || []).sort()
    const sameCompanyTypes =
      searchCompanyTypes.length === currentCompanyTypes.length &&
      searchCompanyTypes.every((type, idx) => type === currentCompanyTypes[idx])
    const sameRemote = Boolean(search.remote_only) === Boolean(currentView.remoteOnly)
    if (currentView.viewType === 'variant') {
      return (
        (search.variant_title || '') === currentView.variantTitle && sameDays && sameCompanyTypes && sameRemote
      )
    }
    return (search.job_title || '') === (currentView.title || '') && sameDays && sameCompanyTypes && sameRemote
  })

  function handleToggleBookmark() {
    if (!user) {
      navigate('/login')
      return
    }
    setBookmarkError(null)
    if (bookmarkedSearch) {
      handleDeleteSearch(bookmarkedSearch.id)
      return
    }
    createSavedSearch({
      name: buildBookmarkName(currentView),
      viewType: currentView.viewType,
      jobTitle: currentView.viewType === 'company' ? null : currentView.title,
      variantTitle: currentView.viewType === 'variant' ? currentView.variantTitle : null,
      postedWithinDays: currentView.viewType === 'company' ? null : currentView.days,
      companyTypes: currentView.viewType === 'company' ? undefined : currentView.companyTypes,
      statusFilter: currentView.viewType === 'status' ? currentView.statusFilter : null,
      companyId: currentView.viewType === 'company' ? currentView.companyId : null,
      remoteOnly: currentView.viewType === 'company' ? undefined : currentView.remoteOnly,
    })
      .then((saved) => setSavedSearches((prev) => [saved, ...prev]))
      .catch((err) => setBookmarkError(err.message))
  }

  // Clicking a bookmarked search in the sidebar restores the EXACT view it
  // was saved under, not just an approximation of it — a variant bookmark
  // re-enters the same drilled-down variant view (not a plain title search
  // for that variant's name), a company bookmark goes straight back to
  // that company's "See them all" list, and a status bookmark re-enters
  // Track Applications on the same radio.
  function handleApplySearch(search) {
    if (search.view_type === 'status') {
      setSelectedVariant(null)
      setSelectedCompany(null)
      setSelectedStatus(search.status_filter)
      return
    }
    if (search.view_type === 'company') {
      setSelectedVariant(null)
      setSelectedStatus(null)
      setSelectedCompany({ id: search.company_id, name: search.company_name || 'this company' })
      return
    }
    const applied = {
      title: search.job_title || '',
      postedDays: search.posted_within_days != null ? String(search.posted_within_days) : '',
      companyTypes: search.company_types || [DEFAULT_COMPANY_TYPE],
      remoteOnly: Boolean(search.remote_only),
    }
    setFilters(applied)
    setAppliedFilters(applied)
    setSelectedCompany(null)
    setSelectedStatus(null)
    setSelectedVariant(search.view_type === 'variant' ? search.variant_title || '' : null)
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
        <div className="flex flex-col items-stretch gap-6 md:flex-row">
          <div ref={sidebarRef} className="border border-line p-5 md:w-72 md:shrink-0">
            <FilterSidebar
              filters={filters}
              onFilterChange={setFilters}
              onUpdateListings={handleUpdateListings}
              savedSearches={savedSearches}
              onApplySearch={handleApplySearch}
              onDeleteSearch={handleDeleteSearch}
              loggedIn={Boolean(user)}
              selectedStatus={selectedStatus}
              onSelectStatus={handleSelectStatus}
              companyTypeCounts={companyTypeCounts}
              companyTypeCountsLoading={companyTypeCountsLoading}
            />
          </div>

          <div className="min-w-0 flex-1 border border-line">
            <div className="relative border-b border-line py-4 text-center">
              <div className="absolute right-4 top-4 flex flex-col items-end gap-1">
                <button
                  type="button"
                  onClick={handleToggleBookmark}
                  className="flex items-center gap-1.5 text-xs font-medium text-ink-soft hover:text-ink"
                >
                  <span
                    aria-hidden="true"
                    className={`text-xl leading-none ${bookmarkedSearch ? 'text-ember' : 'text-ink-soft'}`}
                  >
                    {bookmarkedSearch ? '★' : '☆'}
                  </span>
                  Bookmark Search
                </button>
                {bookmarkError && (
                  <p className="max-w-[200px] text-right text-xs text-ember">{bookmarkError}</p>
                )}
              </div>
              <h1 className="text-xl font-semibold text-ink">Job Listings</h1>
              <button
                type="button"
                onClick={scrollToFilters}
                className="mt-1 text-sm text-ember underline decoration-line underline-offset-2 hover:text-flame md:hidden"
              >
                Search Criteria
              </button>
              {!loading && (
                <p className="mt-1 text-xs text-ink-soft">
                  {totalCount} Job{totalCount === 1 ? '' : 's'} in current search
                </p>
              )}
            </div>

            <ActiveFiltersBar
              filters={appliedFilters}
              onChange={handleActiveFiltersChange}
              onJumpToTitleMatch={handleJumpToTitleMatch}
              selectedVariant={selectedVariant}
              selectedCompany={selectedCompany}
              selectedStatus={selectedStatus}
              onReturnToFullList={handleReturnToFullList}
              titleVariants={titleVariants}
              titleVariantsLoading={titleVariantsLoading}
              showVariants={showVariants}
              onToggleVariants={handleToggleVariants}
              variantCounts={variantCounts}
              variantCountsLoading={variantCountsLoading}
              onSelectVariant={handleSelectVariant}
              scopedCount={loading ? null : totalCount}
            />

            {error ? (
              <div className="border border-dashed border-line m-5 p-10 text-center text-sm text-ink-soft">
                Couldn't load job listings ({error}). Check that the backend is running and
                reachable.
              </div>
            ) : !loading && jobs.length === 0 ? (
              <div className="border border-dashed border-line m-5 p-10 text-center text-sm text-ink-soft">
                No roles match those filters yet. Try widening your search or checking
                back after the next scrape.
              </div>
            ) : (
              <div className="divide-y divide-line">
                {jobs.map((job, index) => (
                  <div
                    key={job.id}
                    ref={(el) => {
                      jobCardRefs.current[job.id] = el
                    }}
                    className={
                      job.id === highlightedJobId
                        ? 'ring-2 ring-inset ring-ember transition-shadow'
                        : ''
                    }
                  >
                    <JobCard
                      job={job}
                      status={getStatus(job.id)}
                      onStatusChange={(status) => setStatus(job.id, status)}
                      shaded={index % 2 === 1}
                      canApply={canApply}
                      onRequireSubscription={() => setShowSubscribeModal(true)}
                      onSeeCompanyJobs={handleSeeCompanyJobs}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      <Footer />
    </div>
  )
}