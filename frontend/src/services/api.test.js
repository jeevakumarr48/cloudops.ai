import { afterEach, describe, expect, it, vi } from 'vitest'
import { describeError, getAiRecommendations, getGovernanceSummary, secureApi, setDemoMode } from './api'

afterEach(() => { setDemoMode(false); vi.restoreAllMocks() })

describe('demo routing', () => {
  it('reads the real endpoints normally and the demo endpoints in demo mode', async () => {
    const get = vi.spyOn(secureApi, 'get').mockResolvedValue({ data: {} })
    await getGovernanceSummary()
    setDemoMode(true)
    await getGovernanceSummary(true)
    await getAiRecommendations(true)
    expect(get.mock.calls.map((c) => c[0])).toEqual(['/api/governance/summary', '/api/demo/governance/summary', '/api/demo/ai/recommendations'])
    // The demo is static: no refresh parameter is sent.
    expect(get.mock.calls[1][1]).toEqual({ params: {} })
  })
})

describe('describeError', () => {
  const http = (status, data = {}) => ({ response: { status, data } })
  it('maps auth failures to the sign-in and operator gates', () => {
    expect(describeError(http(401)).kind).toBe('signin')
    expect(describeError(http(403)).kind).toBe('forbidden')
  })
  it('keeps the server message for other errors', () => {
    const result = describeError(http(429, { detail: 'Too many requests.' }))
    expect(result.message).toContain('Too many requests')
  })
})
