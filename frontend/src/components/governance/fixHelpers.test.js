import { describe, expect, it } from 'vitest'
import { IMPACT, fixScript } from './fixHelpers'

const fix = {
  notice: 'CloudOps never runs these commands.',
  summary: 'Turn on versioning.',
  before: [{ label: 'Save state', command: 'aws s3api get-bucket-versioning --bucket b', impact: 'read_only' }],
  steps: [
    { label: 'Enable', command: 'aws s3api put-bucket-versioning --bucket b', impact: 'safe' },
    { label: 'Delete', command: 'aws s3 rb s3://b', impact: 'destructive' },
  ],
  verify: 'aws s3api get-bucket-versioning --bucket b',
}

describe('fixScript', () => {
  it('keeps the notice, the order of steps and the verify command', () => {
    const script = fixScript(fix)
    expect(script.startsWith('# CloudOps never runs these commands.')).toBe(true)
    const order = ['get-bucket-versioning', 'put-bucket-versioning', 'rb s3://b'].map((c) => script.indexOf(c))
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(script).toContain('# --- Check it worked')
  })

  it('marks permanent steps in the copied script', () => {
    expect(fixScript(fix)).toContain('# Delete (PERMANENT)')
  })

  it('skips empty sections', () => {
    const script = fixScript({ ...fix, before: [], verify: null })
    expect(script).not.toContain('Record the current state')
    expect(script).not.toContain('Check it worked')
  })
})

describe('IMPACT labels', () => {
  it('has a tone and label for every impact level the API sends', () => {
    for (const level of ['read_only', 'safe', 'disruptive', 'destructive']) {
      expect(IMPACT[level]).toHaveLength(2)
    }
    expect(IMPACT.destructive[0]).toBe('danger')
  })
})
