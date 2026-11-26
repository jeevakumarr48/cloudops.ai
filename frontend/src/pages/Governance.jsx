import { Fragment, useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw, ShieldCheck } from 'lucide-react'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import AccessGate from '../components/governance/AccessGate'
import SourceStatus from '../components/governance/SourceStatus'
import { CATEGORIES, EVIDENCE_STATES, FINDING_STATUSES, SETTABLE_STATUSES, SEVERITIES, formatDate, label, severityTone, stateTone } from '../components/governance/labels'
import { describeError, getGovernanceFindings, getGovernanceSummary, updateFindingStatus } from '../services/api'

const EMPTY_FILTERS = { category: '', severity: '', evidence_state: '', resource_type: '', status: '' }

function Select({ name, value, options, onChange, all }) {
  return <label className="filter-select"><span>{name}</span>
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{all}</option>
      {options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
    </select>
  </label>
}

function StatusEditor({ finding, onSaved }) {
  const [status, setStatus] = useState(finding.lifecycle.status === 'resolved' ? 'open' : finding.lifecycle.status)
  const [note, setNote] = useState(finding.lifecycle.status_note || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  if (finding.lifecycle.status === 'resolved') return <p className="muted">Resolved findings reopen automatically if the condition is detected again.</p>
  if (!finding.lifecycle.persisted) return <p className="muted">Status changes need the database, which is not configured on this deployment.</p>
  const save = async () => {
    setSaving(true); setError(null)
    try { await updateFindingStatus(finding.finding_id, status, note); onSaved() } catch (err) { setError(describeError(err).message) } finally { setSaving(false) }
  }
  return <div className="status-editor">
    <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Finding status">
      {SETTABLE_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
    </select>
    <input value={note} maxLength={500} placeholder="Note (optional, e.g. why this risk is accepted)" onChange={(e) => setNote(e.target.value)} aria-label="Status note" />
    <Button size="sm" variant="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save status'}</Button>
    {error && <span className="form-error">{error}</span>}
    <span className="muted">Changing status records a decision only. Nothing in AWS is changed.</span>
  </div>
}

function FindingDetail({ finding, isOperator, onSaved }) {
  const p = finding.priority || {}
  return <div className="finding-detail">
    <div className="detail-grid">
      <section><h4>What was found</h4><p>{finding.description || finding.title}</p>
        <h4>Evidence</h4><ul className="evidence-list">{finding.evidence.map((e) => <li key={e.id}><code>{e.source}</code> {e.observation}</li>)}</ul>
        {finding.missing_information?.length > 0 && <><h4>Missing information</h4><ul>{finding.missing_information.map((m) => <li key={m}>{m}</li>)}</ul></>}
      </section>
      <section><h4>Recommended review</h4><p>{finding.recommendation || 'Review with the resource owner.'}</p>
        {finding.remediation_steps?.length > 0 && <ol>{finding.remediation_steps.map((s) => <li key={s}>{s}</li>)}</ol>}
        <h4>Priority {p.score}</h4>
        <p className="muted mono">{p.formula}</p>
        {p.inputs && <p className="muted">Severity {p.inputs.severity}, exposure {p.inputs.exposure}, financial {p.inputs.financial}, confidence ×{p.inputs.confidence}, effort {p.inputs.effort}, risk {p.inputs.risk}</p>}
        <h4>Lifecycle</h4>
        <p className="muted">First detected {formatDate(finding.lifecycle.first_detected)} · last detected {formatDate(finding.lifecycle.last_detected)}{finding.lifecycle.times_reopened ? ` · reopened ${finding.lifecycle.times_reopened}×` : ''}</p>
        {finding.lifecycle.status_note && <p className="muted">Note: {finding.lifecycle.status_note}</p>}
      </section>
    </div>
    {isOperator && <StatusEditor key={finding.lifecycle.status} finding={finding} onSaved={onSaved} />}
  </div>
}

function Governance({ isOperator, onSignIn, sessionKey }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [summary, setSummary] = useState(null)
  const [findings, setFindings] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null)
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
    if (refresh) params.refresh = true
    if (filters.status === 'resolved') params.include_resolved = true
    try {
      const [s, f] = await Promise.all([getGovernanceSummary(false), getGovernanceFindings(params)])
      setSummary(s.data); setFindings(f.data)
    } catch (err) {
      setError(describeError(err)); setSummary(null); setFindings(null)
    } finally { setLoading(false) }
  }, [filters])

  useEffect(() => {
    const timer = window.setTimeout(() => load(false), 0)
    return () => window.clearTimeout(timer)
  }, [load, sessionKey])

  const set = (key) => (value) => setFilters((f) => ({ ...f, [key]: value }))
  const resourceTypes = summary ? Object.keys(summary.by_resource_type || {}) : []
  const bySeverity = summary?.by_severity || {}
  const rows = findings?.findings || []

  return <main className="dashboard-content">
    <div className="page-heading"><div><span className="eyebrow">Unified governance</span><h1>Governance findings</h1><p>Deterministic checks across EC2, S3, RDS and cost data. Every finding cites the AWS evidence it is based on.</p></div>
      <div className="heading-actions">{summary && <span className="data-badge is-live"><i /> Scanned {formatDate(summary.scanned_at)}</span>}<button className="secondary-button" onClick={() => load(true)} disabled={loading} title="Re-scan sources (rate limited)"><RefreshCw size={15} className={loading ? 'spin' : ''} /> Re-scan</button></div></div>
    {error ? <AccessGate error={error} onSignIn={onSignIn} /> : <>
      <section className="stats-grid">
        <StatCard label="Open findings" kind="recommendations" description="Excludes false positives" value={summary ? String(summary.total_findings) : null} loading={loading && !summary} />
        <StatCard label="Critical and high" kind="resources" description="Highest severities" value={summary ? String((bySeverity.CRITICAL || 0) + (bySeverity.HIGH || 0)) : null} loading={loading && !summary} />
        <StatCard label="Confirmed" kind="cost" description="AWS data directly shows it" value={summary ? String(summary.by_evidence_state?.CONFIRMED || 0) : null} loading={loading && !summary} />
        <StatCard label="Need more data" kind="savings" description="Insufficient evidence to decide" value={summary ? String(summary.by_evidence_state?.INSUFFICIENT_EVIDENCE || 0) : null} loading={loading && !summary} />
      </section>
      <SourceStatus sources={summary?.sources} />
      <section className="panel">
        <div className="panel-heading"><div><span className="eyebrow">Prioritized</span><h2>Findings</h2><p>Sorted by priority score. Select a row for evidence, scoring and lifecycle.</p></div><ShieldCheck className="panel-heading-icon" size={20} /></div>
        <div className="table-toolbar filters-row">
          <Select name="Category" value={filters.category} options={CATEGORIES} onChange={set('category')} all="All categories" />
          <Select name="Severity" value={filters.severity} options={SEVERITIES} onChange={set('severity')} all="All severities" />
          <Select name="Evidence" value={filters.evidence_state} options={EVIDENCE_STATES} onChange={set('evidence_state')} all="All evidence states" />
          <Select name="Resource" value={filters.resource_type} options={resourceTypes} onChange={set('resource_type')} all="All resource types" />
          <Select name="Status" value={filters.status} options={FINDING_STATUSES} onChange={set('status')} all="Any status" />
          {Object.values(filters).some(Boolean) && <Button variant="text" onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</Button>}
        </div>
        <div className="table-wrap"><table className="findings-table"><thead><tr><th aria-label="Expand" /><th>Priority</th><th>Severity</th><th>Finding</th><th>Resource</th><th>Evidence</th><th>Status</th><th>Last detected</th></tr></thead>
          <tbody>{loading && !findings ? <tr><td colSpan={8}><EmptyState loading /></td></tr>
            : rows.length === 0 ? <tr><td colSpan={8}><EmptyState title="No findings match" description="Nothing was detected for these filters in the sources that could be scanned. Unavailable sources are listed above." /></td></tr>
            : rows.map((f) => { const open = expanded === f.finding_id; return <Fragment key={f.finding_id}>
              <tr className={`finding-tr ${open ? 'is-open' : ''}`} onClick={() => setExpanded(open ? null : f.finding_id)}>
                <td><button className="plain-icon-button" aria-expanded={open} aria-label={open ? 'Collapse' : 'Expand'}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button></td>
                <td><strong>{f.priority?.score ?? '—'}</strong></td>
                <td><Badge tone={severityTone(f.severity)}>{f.severity}</Badge></td>
                <td><strong>{f.title}</strong><span className="sub mono">{f.rule_id}</span></td>
                <td><span className="sub">{f.resource_type}</span><span className="resource-id">{f.resource_id}</span></td>
                <td><Badge tone={stateTone(f.evidence_state)}>{label(f.evidence_state)}</Badge></td>
                <td>{label(f.lifecycle?.status)}</td>
                <td>{formatDate(f.lifecycle?.last_detected)}</td>
              </tr>
              {open && <tr className="detail-tr"><td colSpan={8}><FindingDetail finding={f} isOperator={isOperator} onSaved={() => load(false)} /></td></tr>}
            </Fragment> })}
          </tbody></table></div>
        <div className="pagination"><span>Showing {rows.length} of {findings?.total ?? 0} findings</span><span>Advisory only. CloudOps AI never changes AWS resources.</span></div>
      </section>
    </>}
  </main>
}

export default Governance
