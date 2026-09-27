import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000',
  timeout: 10000,
})

// React talks to FastAPI only. Backend CORS configuration may be required for local development.
export const getHealth = () => api.get('/health')
export const getEc2Resources = () => api.get('/api/resources/ec2')
export const getEc2Metrics = () => api.get('/api/metrics/ec2')
export const getCosts = () => api.get('/api/costs')
export const getInsights = () => api.get('/api/insights')
export const getOverview = () => api.get('/api/overview')
export const getRecommendations = () => api.get('/api/recommendations')

export default api
