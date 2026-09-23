import { Menu, Plus } from 'lucide-react'
import StatusPill from './ui/StatusPill'

function TopBar({ onMenu, onScan }) {
  return (
    <header className="topbar">
      <button type="button" className="icon-button menu-button" onClick={onMenu} aria-label="Open navigation"><Menu size={21} /></button>
      <div className="topbar-context">
        <span className="eyebrow">CloudOps AI</span>
        <span className="context-divider" />
        <span>AWS Account</span>
        <StatusPill tone="warn" className="connected" title="Frontend state only; backend connection is not configured">Not connected</StatusPill>
        <span className="region-label">Region: <b>—</b></span>
      </div>
      <button type="button" className="scan-button" onClick={onScan}><Plus size={16} /> Add a Scan</button>
    </header>
  )
}

export default TopBar
