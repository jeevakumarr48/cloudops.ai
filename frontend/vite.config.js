import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.VITE_API_URL || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    // Same-origin proxy for local development so the session cookie works
    // exactly like the /api rewrite in vercel.json does in production.
    server: { proxy: { '/api': { target, changeOrigin: true }, '/health': { target, changeOrigin: true } } },
  }
})
