// The JobBeggar Brief API (backend: routes/blog.py). Reading is public; liking
// and commenting need a subscriber; writing posts needs an admin.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

function authHeaders() {
  const token = localStorage.getItem('sjh_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(path, { method = 'GET', body, form } = {}) {
  const headers = { ...authHeaders() }
  let payload
  if (form) {
    payload = form
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(`${API_URL}/api/blog${path}`, { method, headers, body: payload })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.error || 'Something went wrong. Please try again.')
    err.status = res.status
    err.code = data.code
    throw err
  }
  return data
}

// Backend returns image paths like /api/blog/images/<id>; make them absolute.
export function imageUrl(path) {
  return path ? `${API_URL}${path}` : null
}

// "/blog/12-my-post" -> 12
export function postIdFromParam(param) {
  const id = parseInt(String(param || ''), 10)
  return Number.isFinite(id) && id > 0 ? id : null
}

export const fetchBlogMe = () => request('/me')
export const fetchPosts = (page = 1) => request(`/posts?page=${page}`)
export const fetchPost = (id) => request(`/posts/${id}`)
export const createPost = (post) => request('/posts', { method: 'POST', body: post })
export const updatePost = (id, post) => request(`/posts/${id}`, { method: 'PUT', body: post })
export const deletePost = (id) => request(`/posts/${id}`, { method: 'DELETE' })
export const toggleLike = (id) => request(`/posts/${id}/like`, { method: 'POST' })
export const fetchComments = (id) => request(`/posts/${id}/comments`)
export const addComment = (id, body) => request(`/posts/${id}/comments`, { method: 'POST', body: { body } })
export const deleteComment = (id) => request(`/comments/${id}`, { method: 'DELETE' })
export const banCommenter = (commentId, { reason, deleteAll }) =>
  request(`/admin/comments/${commentId}/ban`, { method: 'POST', body: { reason, delete_all: deleteAll } })
export const fetchBans = () => request('/admin/bans')
export const unbanUser = (userId) => request(`/admin/bans/${userId}`, { method: 'DELETE' })

export function uploadImage(file) {
  const form = new FormData()
  form.append('image', file)
  return request('/images', { method: 'POST', form })
}

export function formatDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function readingMinutes(text) {
  return Math.max(1, Math.round(String(text || '').split(/\s+/).filter(Boolean).length / 200))
}
