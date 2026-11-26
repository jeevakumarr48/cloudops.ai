import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000',
  timeout: 10000,
})

// React talks to FastAPI only. Backend CORS configuration may be required for local development.
export const getHealth = () => api.get('/health')
export const getEc2Resources = () => api.get('/api/resources/ec2')
export const getEc2Metrics = () => api.get('/api/metrics/ec2')
export const getCosts = (period = 'monthly') => api.get('/api/costs', { params: { period } })
export const getCostForecast = (period = 'monthly') => api.get('/api/costs/forecast', { params: { period } })
export const getInsights = () => api.get('/api/insights')
export const getOverview = () => api.get('/api/overview')
export const getRecommendations = () => api.get('/api/recommendations')

// Account and governance calls carry the HttpOnly session cookie, so they
// always go to the same origin: Vercel rewrites /api/* to the API project in
// production and the Vite dev server proxies it locally (see vite.config.js).
// A cross-site call would not carry a SameSite=Lax cookie.
export const secureApi = axios.create({
  baseURL: '',
  timeout: 30000,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

export const getMe = () => secureApi.get('/api/auth/me')
export const login = (email, password) => secureApi.post('/api/auth/login', { email, password })
export const register = (email, password, displayName) => secureApi.post('/api/auth/register', { email, password, display_name: displayName || null })
export const logout = () => secureApi.post('/api/auth/logout', {})

export const getGovernanceSummary = (refresh = false) => secureApi.get('/api/governance/summary', { params: { refresh } })
export const getGovernanceFindings = (params = {}) => secureApi.get('/api/governance/findings', { params })
export const updateFindingStatus = (findingId, status, note) => secureApi.patch(`/api/governance/findings/${encodeURIComponent(findingId)}`, { status, note: note || null })

export const getAiStatus = () => secureApi.get('/api/ai/status')
export const getAiRecommendations = (refresh = false) => secureApi.get('/api/ai/recommendations', { params: { refresh } })
export const analyzeWithAi = (body) => secureApi.post('/api/ai/analyze', body, { timeout: 300000 })
export const sendRecommendationFeedback = (recommendationId, decision, note) => secureApi.post(`/api/ai/recommendations/${encodeURIComponent(recommendationId)}/feedback`, { decision, note: note || null })

export const getSecurityStatus = () => secureApi.get('/api/security/status')
export const getAuditLog = (params = {}) => secureApi.get('/api/security/audit', { params })

// Turns an API error into a user-facing state without leaking internals.
export function describeError(error) {
  const status = error?.response?.status
  const detail = error?.response?.data?.detail
  if (error?.response?.data?.code === 'origin_not_allowed') return { kind: 'forbidden', message: error.response.data.error }
  if (status === 401) return { kind: 'signin', message: 'Sign in as a CloudOps AI operator to view this.' }
  if (status === 403) return { kind: 'forbidden', message: typeof detail === 'string' ? detail : 'Operator access required.' }
  if (status === 503) return { kind: 'unavailable', message: 'Accounts are not enabled on this deployment yet (no database configured).' }
  if (status === 429) return { kind: 'limited', message: typeof detail === 'string' ? detail : 'Too many requests. Try again later.' }
  if (status === 422) return { kind: 'invalid', message: Array.isArray(detail) ? detail.map((d) => d.msg).join(' ') : (detail || 'The request was not valid.') }
  if (!error?.response) return { kind: 'offline', message: 'The CloudOps AI API could not be reached.' }
  return { kind: 'error', message: typeof detail === 'string' ? detail : 'Something went wrong.' }
}

export default api
