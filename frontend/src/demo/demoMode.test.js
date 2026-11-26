import { describe, expect, it } from 'vitest'
import { initialDemo, rememberDemo } from './demoMode'

const at = (search) => window.history.replaceState(null, '', `/${search}`)

describe('demo mode', () => {
  it('is off by default', () => {
    at('')
    expect(initialDemo()).toBe(false)
  })

  it('turns on from the ?demo=1 link and off from ?demo=0', () => {
    at('?demo=1')
    expect(initialDemo()).toBe(true)
    at('?demo=0')
    expect(initialDemo()).toBe(false)
  })

  it('remembers the choice for the tab and keeps the link shareable', () => {
    at('')
    rememberDemo(true)
    expect(window.location.search).toBe('?demo=1')
    window.history.replaceState(null, '', '/')
    expect(initialDemo()).toBe(true)
    rememberDemo(false)
    expect(window.location.search).toBe('')
    expect(initialDemo()).toBe(false)
  })
})
