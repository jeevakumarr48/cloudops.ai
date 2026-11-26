import { useCallback, useEffect, useState } from 'react'
import { KeyRound, LockKeyhole, RefreshCw } from 'lucide-react'
import EmptyState from '../components/EmptyState'
import StatusPill from '../components/ui/StatusPill'
import AccessGate from '../components/governance/AccessGate'
import { formatDate } from '../components/governance/labels'
import { describeError, getAuditLog, getSecurityStatus } from '../services/api'

const MODES = {
  oidc: 'Vercel OIDC role (no stored keys)',
  assume_role: 'Assumed role (temporary credentials)',
  default: 'Default credential chain',
}

function Security({ onSignIn, sessionKey }) {
  const [status, setStatus] = useState(null)
  const [audit, setAudit] = useState(null)
  const [action, setAction] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [s, a] = await Promise.all([getSecurityStatus(), getAuditLog(action ? { action } : {})])
      setStatus(s.data); setAudit(a.data)
    } catch (err) { setError(describeError(err)) } finally { setLoading(false) }
  }, [action])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load, sessionKey])

  const creds = status?.aws_credentials
  const actions = [...new Set((audit?.events || []).map((e) => e.action))].sort()

  return <main className="dashboard-content">
    <div className="page-heading"><div><span className="eyebrow">Operator only</span><h1>Security</h1><p>How this deployment reaches AWS, and every recorded sign-in and decision.</p></div>
      <div className="heading-actions"><button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button></div></div>
    {error ? <AccessGate error={error} onSignIn={onSignIn} /> : <>
      <div className="two-column">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">AWS access</span><h2>Credentials</h2><p>Read-only. Key material is never shown or sent to the browser.</p></div><KeyRound className="panel-heading-icon" size={20} /></div>
          {!creds ? <EmptyState loading={loading} /> : <dl className="ai-status">
            <div><dt>Mode</dt><dd>{MODES[creds.mode] || creds.mode}</dd></div>
            <div><dt>Credential type</dt><dd><StatusPill tone={creds.temporary ? 'ok' : creds.credentials === 'none' ? 'neutral' : 'warn'}>{creds.credentials === 'none' ? 'None found' : creds.temporary ? 'Temporary' : 'Long-lived keys'}</StatusPill></dd></div>
          </dl>}
          {creds?.recommendation && <p className="muted">{creds.recommendation} See docs/iam/README.md.</p>}
        </section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Deployment</span><h2>Settings in effect</h2><p>Changed only through environment variables.</p></div><LockKeyhole className="panel-heading-icon" size={20} /></div>
          {status && <dl className="ai-status">
            <div><dt>Secure session cookie</dt><dd>{status.session_cookie_secure ? 'On' : 'Off (local only)'}</dd></div>
            <div><dt>Self-registration</dt><dd>{status.registration_open ? 'Open' : 'Closed'}</dd></div>
            <div><dt>Findings public</dt><dd>{status.public_security_findings ? 'Yes' : 'No, operators only'}</dd></div>
            <div><dt>Operators</dt><dd>{status.operators_configured}</dd></div>
          </dl>}
          {status && <p className="muted">Changes to AWS: {status.changes_to_aws}.</p>}
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">Audit trail</span><h2>Recent events</h2><p>Sign-ins, status changes, AI runs and recommendation decisions. IP addresses are stored only as short hashes.</p></div></div>
        <div className="table-toolbar filters-row"><label className="filter-select"><span>Action</span><select value={action} onChange={(e) => setAction(e.target.value)}><option value="">All actions</option>{[...new Set([...actions, action].filter(Boolean))].map((a) => <option key={a} value={a}>{a}</option>)}</select></label></div>
        <div className="table-wrap"><table className="findings-table"><thead><tr><th>When</th><th>Action</th><th>User</th><th>Target</th><th>Detail</th></tr></thead>
          <tbody>{loading && !audit ? <tr><td colSpan={5}><EmptyState loading /></td></tr>
            : !audit?.events?.length ? <tr><td colSpan={5}><EmptyState title="No events" /></td></tr>
            : audit.events.map((e) => <tr key={e.id}><td>{formatDate(e.created_at)}</td><td className="mono">{e.action}</td><td>{e.user_email || '—'}</td><td className="mono">{e.target || '—'}</td><td>{e.detail || '—'}</td></tr>)}</tbody></table></div>
        <div className="pagination"><span>Showing {audit?.total ?? 0} most recent events</span></div>
      </section>
    </>}
  </main>
}

export default Security
