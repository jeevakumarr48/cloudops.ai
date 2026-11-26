import { useEffect, useState } from 'react'
import { LogIn, LogOut, Menu, Plus, UserRound } from 'lucide-react'
import StatusPill from './ui/StatusPill'
import { getHealth } from '../services/api'

function TopBar({ onMenu, onScan, session, onSignIn }) {
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
      <div className="topbar-actions">
        {session?.status === 'signed_in' ? <span className="account-chip" title={session.isOperator ? 'Operator: can view and act on governance data' : 'Signed in (not an operator)'}>
          <UserRound size={15} /><span className="account-email">{session.me.user.display_name || session.me.user.email}</span>
          {session.isOperator && <span className="account-role">Operator</span>}
          <button type="button" className="plain-icon-button" onClick={session.logout} aria-label="Sign out" title="Sign out"><LogOut size={15} /></button>
        </span> : session?.status === 'signed_out' && session.accountsAvailable ? <button type="button" className="secondary-button" onClick={onSignIn}><LogIn size={15} /> Sign in</button> : null}
        <button type="button" className="scan-button" onClick={onScan}><Plus size={16} /> Add a Scan</button>
      </div>
    </header>
  )
}

export default TopBar
