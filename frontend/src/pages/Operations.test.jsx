import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import Operations from './Operations'
import * as api from '../services/api'

const status = {
  build: { version: '1.0.0', commit: 'abc1234', environment: 'production', python: '3.12.8', log_format: 'json' },
  checks: { database: { status: 'ok', latency_ms: 3.2 }, aws_credentials: { mode: 'oidc' }, ai_provider: 'none' },
  budgets: { cost_explorer_requests_this_month: { used: 70, limit: 75, note: 'Billed.' }, ai_calls_today: { used: 0, limit: 20 } },
  scans: { recent: [{ started_at: '2026-11-26T10:00:00+00:00', duration_ms: 1200, finding_count: 4,
    sources: { s3: { status: 'ok', duration_ms: 800 }, cost: { status: 'unavailable', duration_ms: 50 } } }],
  by_source: { s3: { scans: 1, success_rate: 1, avg_duration_ms: 800, last_status: 'ok' } } },
  requests: { scope: 'this instance since it started', started_at: '2026-11-26T09:00:00+00:00', total_requests: 10,
    server_errors: 0, dependency_unavailable: 2, latency_ms: { p50: 12, p95: 140 }, top_routes: [{ route: '/health', requests: 5, server_errors: 0 }] },
}

describe('Operations', () => {
  it('shows health, budgets near their cap, scans and request metrics', async () => {
    vi.spyOn(api, 'getOpsStatus').mockResolvedValue({ data: status })
    render(<Operations onSignIn={() => {}} sessionKey="k" />)
    expect(await screen.findByText(/Build 1.0.0 · abc1234/)).toBeInTheDocument()
    expect(screen.getByText('70 of 75')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Cost Explorer requests this month' }).firstChild).toHaveClass('budget-fill--danger')
    expect(screen.getByText('1.2 s')).toBeInTheDocument()
    expect(screen.getByText('/health')).toBeInTheDocument()
  })

  it('asks a signed-out visitor to sign in', async () => {
    vi.spyOn(api, 'getOpsStatus').mockRejectedValue({ response: { status: 401, data: {} } })
    render(<Operations onSignIn={() => {}} sessionKey="k" />)
    expect(await screen.findByText('Sign in to view governance data')).toBeInTheDocument()
  })
})
