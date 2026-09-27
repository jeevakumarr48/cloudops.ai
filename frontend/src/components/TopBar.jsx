import { useEffect, useState } from 'react'
import { Menu, Plus } from 'lucide-react'
import StatusPill from './ui/StatusPill'
import { getHealth } from '../services/api'

function TopBar({ onMenu, onScan }) {
  const [connection, setConnection] = useState('checking')

  useEffect(() => {
    let active = true
    getHealth()
      .then(() => { if (active) setConnection('connected') })
      .catch(() => { if (active) setConnection('offline') })
    return () => { active = false }
  }, [])

  const status = {
    checking: { tone: 'neutral', label: 'Checking…' },
    connected: { tone: 'ok', label: 'Connected' },
    offline: { tone: 'warn', label: 'Offline' },
  }[connection]

  return (
    <header className="topbar">
      <button type="button" className="icon-button menu-button" onClick={onMenu} aria-label="Open navigation"><Menu size={21} /></button>
      <div className="topbar-context">
        <span className="eyebrow">CloudOps AI</span>
        <span className="context-divider" />
        <span>AWS Account</span>
        <StatusPill tone={status.tone} className="connected" title="Live connectivity to the CloudOps AI API (/health)">{status.label}</StatusPill>
        <span className="region-label">Region: <b>—</b></span>
      </div>
      <button type="button" className="scan-button" onClick={onScan}><Plus size={16} /> Add a Scan</button>
    </header>
  )
}

export default TopBar
