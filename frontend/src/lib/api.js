const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

const FUNDING_STAGE_LABELS = {
  seed: 'Seed',
  series_a: 'Series A',
  series_b: 'Series B',
  series_c_plus: 'Series C+',
  public: 'Public',
  bootstrapped: 'Bootstrapped',
  unknown: '',
}

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
    department: row.department || '',
    location: row.location || '',
    datePosted: row.date_posted,
    match: row.match ?? null,
    funding: FUNDING_STAGE_LABELS[row.funding] ?? row.funding ?? '',
    otherJobsAtCompany: row.other_jobs_at_company || 0,
    status: row.status,
    reasonRejected: row.reason_rejected,
  }
}

export async function fetchJobs(filters) {
  const params = new URLSearchParams()
  if (filters.title) params.set('title', filters.title)
  if (filters.postedDays) params.set('posted_days', filters.postedDays)
  if (filters.funding) params.set('funding', filters.funding)
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

export async function createSavedSearch({ name, jobTitle, variants, postedWithinDays, fundingFilter }) {
  const res = await fetch(`${API_URL}/api/saved-searches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      name,
      job_title: jobTitle || null,
      variants,
      posted_within_days: postedWithinDays || null,
      funding_filter: fundingFilter,
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