import { createContext, useContext } from 'react'

// Demo mode shows sample data from the public /api/demo endpoints, so anyone
// can explore the console without an account or an AWS connection.
export const DemoContext = createContext({ demo: false, enterDemo: () => {}, exitDemo: () => {} })
export const useDemo = () => useContext(DemoContext)

const KEY = 'cloudops-demo'

export function initialDemo() {
  if (typeof window === 'undefined') return false
  const param = new URLSearchParams(window.location.search).get('demo')
  if (param !== null) return param !== '0' && param !== 'false'
  return window.sessionStorage.getItem(KEY) === '1'
}

export function rememberDemo(on) {
  window.sessionStorage.setItem(KEY, on ? '1' : '0')
  const url = new URL(window.location.href)
  if (on) url.searchParams.set('demo', '1'); else url.searchParams.delete('demo')
  window.history.replaceState(null, '', url)
}

// Pages that have demo data; the others read live AWS data only.
export const DEMO_PAGES = ['Governance', 'Recommendations']
