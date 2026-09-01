const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

function authHeaders() {
  const token = localStorage.getItem('sjh_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Maps a /api/jobs row (snake_case, DB shape) to the camelCase shape
// JobCard / JobListings already render.
function mapJob(row) {
  return {
    id: row.id,
    title: row.title,
    company: row.company,
    companyType: row.company_type,
    department: row.department || '',
    location: row.location || '',
    datePosted: row.date_posted,
    otherJobsAtCompany: row.other_jobs_at_company || 0,
    companyId: row.company_id,
    status: row.status,
    reasonRejected: row.reason_rejected,
    // 0-100 "how well does this match what you searched" score, blending
    // title and description word-overlap against the typed job title. null
    // when there was no title search to score against (e.g. browsing "All
    // jobs at X" or Track Applications), in which case the card shows no
    // ring.
    matchPercent: row.search_match_percent ?? null,
    // Prefer the specific posting URL; fall back to the company's site if
    // this posting doesn't have one on file (some career-page scrapes miss
    // a per-job link). Null means we genuinely have nowhere to send them.
    applyUrl: row.source_url || row.company_website || null,
  }
}

export async function fetchJobs(filters) {
  const params = new URLSearchParams()
  if (filters.title) params.set('title', filters.title)
  if (filters.postedDays) params.set('posted_days', filters.postedDays)
  // Handle companyTypes as an array - append each type
  if (filters.companyTypes && filters.companyTypes.length > 0) {
    for (const companyType of filters.companyTypes) {
      params.append('company_type', companyType)
    }
  }
  if (filters.companyId) params.set('company_id', filters.companyId)
  if (filters.status) params.set('status', filters.status)
  if (filters.remoteOnly) params.set('remote_only', '1')
  for (const variantTitle of filters.variantTitles || []) {
    params.append('variant_title', variantTitle)
  }
  params.set('limit', 500)

  const res = await fetch(`${API_URL}/api/jobs?${params.toString()}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Failed to load jobs (${res.status})`)

  const data = await res.json()
  return {
    jobs: data.jobs.map(mapJob),
    totalCount: data.total_count,
  }
}

async function parseErrorOr(res, fallback) {
  const body = await res.json().catch(() => null)
  return body?.error || fallback
}

export async function fetchSavedSearches() {
  const res = await fetch(`${API_URL}/api/saved-searches`, { headers: authHeaders() })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to load saved searches (${res.status})`))
  const data = await res.json()
  return data.saved_searches
}

export async function createSavedSearch({
  name,
  viewType = 'search',
  jobTitle,
  variantTitle,
  postedWithinDays,
  companyTypes,
  statusFilter,
  companyId,
  remoteOnly,
}) {
  const res = await fetch(`${API_URL}/api/saved-searches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      name,
      view_type: viewType,
      job_title: jobTitle || null,
      variant_title: variantTitle || null,
      posted_within_days: postedWithinDays || null,
      company_types: companyTypes || [],
      status_filter: statusFilter || null,
      company_id: companyId || null,
      remote_only: Boolean(remoteOnly),
    }),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to save search (${res.status})`))
  return res.json()
}

export async function deleteSavedSearch(id) {
  const res = await fetch(`${API_URL}/api/saved-searches/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok && res.status !== 204) {
    throw new Error(await parseErrorOr(res, `Failed to delete saved search (${res.status})`))
  }
}

export async function setJobStatus(jobId, status, reasonRejected) {
  const res = await fetch(`${API_URL}/api/job-status/${jobId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ status, reason_rejected: reasonRejected || null }),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to update status (${res.status})`))
  return res.json()
}

export async function clearJobStatus(jobId) {
  const res = await fetch(`${API_URL}/api/job-status/${jobId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok && res.status !== 204) {
    throw new Error(await parseErrorOr(res, `Failed to clear status (${res.status})`))
  }
}

export async function submitContactMessage({ name, email, subject, message, website }) {
  const res = await fetch(`${API_URL}/api/contact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, subject, message, website }),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to send message (${res.status})`))
  return res.json()
}

export async function fetchTitleVariants(title) {
  const params = new URLSearchParams({ title })
  const res = await fetch(`${API_URL}/api/title-variants?${params.toString()}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to load title variants (${res.status})`))
  const data = await res.json()
  return data.variants
}

// Site-wide totals for the landing page counters -- { companyCount, jobCount }
// across every Company Database combined.
export async function fetchSiteStats() {
  const res = await fetch(`${API_URL}/api/stats`)
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to load stats (${res.status})`))
  const data = await res.json()
  return { companyCount: data.company_count, jobCount: data.job_count }
}

// Total active jobs in each company database, unfiltered -- not scoped to
// title, posted-days, or any other search filter, e.g.
// { funded: 1025, fortune500: 1500, both: 2525 }. Drives the counts shown
// next to all three Company Database radios in the sidebar.
export async function fetchCompanyTypeCounts() {
  const res = await fetch(`${API_URL}/api/jobs/company-type-counts`, {
    headers: authHeaders(),
  })
  if (!res.ok) {
    throw new Error(await parseErrorOr(res, `Failed to load company type counts (${res.status})`))
  }
  const data = await res.json()
  return data.counts
}