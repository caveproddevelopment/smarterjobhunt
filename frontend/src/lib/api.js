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
  if (filters.companyType && filters.companyType !== 'both') {
    params.set('company_type', filters.companyType)
  }
  if (filters.companyId) params.set('company_id', filters.companyId)
  if (filters.status) params.set('status', filters.status)
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

export async function createSavedSearch({ name, jobTitle, postedWithinDays }) {
  const res = await fetch(`${API_URL}/api/saved-searches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      name,
      job_title: jobTitle || null,
      posted_within_days: postedWithinDays || null,
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

export async function fetchTitleVariants(title) {
  const params = new URLSearchParams({ title })
  const res = await fetch(`${API_URL}/api/title-variants?${params.toString()}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to load title variants (${res.status})`))
  const data = await res.json()
  return data.variants
}

// How many active jobs match each variant title on its own (never OR'd
// together) -- e.g. { "Product Owner": 4, "Senior Product Manager": 0 }.
// Drives which "Also matching" pills are clickable.
export async function fetchVariantCounts(variantTitles, { postedDays, companyType } = {}) {
  if (!variantTitles || variantTitles.length === 0) return {}

  const params = new URLSearchParams()
  for (const variantTitle of variantTitles) {
    params.append('variant_title', variantTitle)
  }
  if (postedDays) params.set('posted_days', postedDays)
  if (companyType && companyType !== 'both') params.set('company_type', companyType)

  const res = await fetch(`${API_URL}/api/jobs/variant-counts?${params.toString()}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(await parseErrorOr(res, `Failed to load variant counts (${res.status})`))
  const data = await res.json()
  return data.counts
}