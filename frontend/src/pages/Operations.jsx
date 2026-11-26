import { useCallback, useEffect, useState } from 'react'
import { Activity, Gauge, HeartPulse, RefreshCw, Wallet } from 'lucide-react'
import EmptyState from '../components/EmptyState'
import StatusPill from '../components/ui/StatusPill'
import AccessGate from '../components/governance/AccessGate'
import { formatDate } from '../components/governance/labels'
import { describeError, getOpsStatus } from '../services/api'

const SOURCE_NAMES = { ec2: 'EC2', s3: 'S3', rds: 'RDS', cost: 'Cost Explorer' }
const checkTone = (status) => ({ ok: 'ok', not_configured: 'neutral' }[status] || 'warn')
const ms = (value) => (value == null ? '—' : value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`)

function Budget({ label, used, limit, note }) {
  const share = used != null && limit ? Math.min(1, used / limit) : 0
  const tone = share >= 0.9 ? 'danger' : share >= 0.6 ? 'warn' : 'ok'
  return <div className="budget">
    <div className="budget-head"><span>{label}</span><strong>{used ?? '—'} of {limit}</strong></div>
    <div className="budget-bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used ?? 0}><i className={`budget-fill budget-fill--${tone}`} style={{ width: `${share * 100}%` }} /></div>
    {note && <p className="muted">{note}</p>}
  </div>
}

function Operations({ onSignIn, sessionKey }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { setData((await getOpsStatus()).data) } catch (err) { setError(describeError(err)) } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [load, sessionKey])

  const build = data?.build
  const checks = data?.checks
  const req = data?.requests
  const scans = data?.scans?.recent || []
  const bySource = data?.scans?.by_source || {}

  return <main className="dashboard-content">
    <div className="page-heading"><div><span className="eyebrow">Operator only</span><h1>Operations</h1><p>Health, spend limits, scan history and request metrics. Loading this page makes no AWS or AI calls.</p></div>
      <div className="heading-actions"><button className="secondary-button" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button></div></div>
    {error ? <AccessGate error={error} onSignIn={onSignIn} /> : !data ? <div className="panel"><EmptyState loading /></div> : <>
      <div className="two-column">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Health</span><h2>Dependencies</h2><p>Build {build.version}{build.commit ? ` · ${build.commit}` : ''} · {build.environment} · Python {build.python} · {build.log_format} logs</p></div><HeartPulse className="panel-heading-icon" size={20} /></div>
          <dl className="ai-status">
            <div><dt>Database</dt><dd><StatusPill tone={checkTone(checks.database.status)}>{checks.database.status.replace('_', ' ')}</StatusPill>{checks.database.latency_ms != null && <span className="muted"> {checks.database.latency_ms} ms</span>}</dd></div>
            <div><dt>AWS credentials</dt><dd>{checks.aws_credentials.mode}</dd></div>
            <div><dt>AI provider</dt><dd>{checks.ai_provider}</dd></div>
          </dl>
        </section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Spend guardrails</span><h2>Budgets</h2><p>Hard caps keep billed calls under the $1 a month target.</p></div><Wallet className="panel-heading-icon" size={20} /></div>
          <Budget label="Cost Explorer requests this month" used={data.budgets.cost_explorer_requests_this_month.used} limit={data.budgets.cost_explorer_requests_this_month.limit} note={data.budgets.cost_explorer_requests_this_month.note} />
          <Budget label="AI provider calls today" used={data.budgets.ai_calls_today.used} limit={data.budgets.ai_calls_today.limit} />
        </section>
      </div>
      <section className="panel ops-section"><div className="panel-heading"><div><span className="eyebrow">Governance scans</span><h2>Source health</h2><p>From the last {scans.length} scan(s). Scans are reused for 60 seconds, so this is not one row per page view.</p></div><Activity className="panel-heading-icon" size={20} /></div>
        {scans.length === 0 ? <EmptyState title="No scans recorded yet" description="Open Governance or Recommendations to run the first scan." /> : <>
          <div className="source-cards">{Object.entries(bySource).map(([name, s]) => <div key={name} className="source-card">
            <span className="sub">{SOURCE_NAMES[name] || name}</span>
            <strong>{Math.round(s.success_rate * 100)}%</strong><span className="muted">success over {s.scans} · avg {ms(s.avg_duration_ms)}</span>
            <StatusPill tone={s.last_status === 'ok' ? 'ok' : 'warn'}>last: {s.last_status}</StatusPill>
          </div>)}</div>
          <div className="table-wrap"><table className="findings-table"><thead><tr><th>Started</th><th>Duration</th><th>Findings</th><th>Sources</th></tr></thead>
            <tbody>{scans.slice(0, 10).map((s) => <tr key={s.started_at}><td>{formatDate(s.started_at)}</td><td>{ms(s.duration_ms)}</td><td>{s.finding_count}</td>
              <td><span className="scan-sources">{Object.entries(s.sources).map(([n, src]) => <StatusPill key={n} tone={src.status === 'ok' ? 'ok' : 'warn'} title={`${ms(src.duration_ms)}`}>{SOURCE_NAMES[n] || n} {ms(src.duration_ms)}</StatusPill>)}</span></td></tr>)}</tbody></table></div>
        </>}
      </section>
      <section className="panel ops-section"><div className="panel-heading"><div><span className="eyebrow">API requests</span><h2>Traffic and latency</h2><p>Counted in memory on {req.scope}, started {formatDate(req.started_at)}. On Vercel each instance keeps its own counts.</p></div><Gauge className="panel-heading-icon" size={20} /></div>
        <dl className="ai-status ops-metrics">
          <div><dt>Requests</dt><dd>{req.total_requests}</dd></div>
          <div><dt>Server errors</dt><dd>{req.server_errors}</dd></div>
          <div><dt>AWS or database unavailable (503)</dt><dd>{req.dependency_unavailable}</dd></div>
          <div><dt>Latency p50</dt><dd>{ms(req.latency_ms.p50)}</dd></div>
          <div><dt>Latency p95</dt><dd>{ms(req.latency_ms.p95)}</dd></div>
        </dl>
        {req.top_routes.length > 0 && <div className="table-wrap"><table className="findings-table"><thead><tr><th>Route</th><th>Requests</th><th>Server errors</th></tr></thead>
          <tbody>{req.top_routes.map((r) => <tr key={r.route}><td className="mono">{r.route}</td><td>{r.requests}</td><td>{r.server_errors}</td></tr>)}</tbody></table></div>}
      </section>
    </>}
  </main>
}

export default Operations
