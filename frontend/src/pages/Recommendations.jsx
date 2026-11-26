import { useCallback, useEffect, useState } from 'react'
import { Bot, CheckCircle2, Lightbulb, RefreshCw, ShieldAlert, Sparkles } from 'lucide-react'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/EmptyState'
import AccessGate from '../components/governance/AccessGate'
import SourceStatus from '../components/governance/SourceStatus'
import { DECISIONS, SEVERITIES, formatDate, label, severityTone, stateTone } from '../components/governance/labels'
import { analyzeWithAi, describeError, getAiRecommendations, getAiStatus, sendRecommendationFeedback } from '../services/api'

const OUTCOMES = {
  rewritten: 'rewritten by AI and validated', cached: 'already had a validated AI version',
  rejected: 'AI text rejected by the validator (template kept)', previously_rejected: 'skipped: AI text for this evidence was already rejected',
  provider_error: 'AI provider error (template kept)', no_provider: 'no AI provider configured (template kept)',
  daily_limit_reached: 'daily AI call limit reached (template kept)',
}

function Field({ n, title, children }) {
  return <div className="rec-field"><span className="rec-field-n" aria-hidden="true">{n}</span><div><h4>{title}</h4>{children}</div></div>
}

function List({ items, empty = 'None' }) {
  if (!items?.length) return <p className="muted">{empty}</p>
  return <ul>{items.map((i) => <li key={i}>{i}</li>)}</ul>
}

function Feedback({ rec, isOperator, onSaved }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const current = rec.feedback
  const send = async (decision) => {
    setBusy(decision); setError(null)
    try { await sendRecommendationFeedback(rec.recommendation_id, decision, note); setNote(''); onSaved() } catch (err) { setError(describeError(err).message) } finally { setBusy(null) }
  }
  return <div className="rec-feedback">
    {current && <p className="muted"><CheckCircle2 size={13} /> {label(current.decision)} · {formatDate(current.recorded_at)}{current.note ? ` · “${current.note}”` : ''}</p>}
    {isOperator ? <div className="rec-feedback-row">
      <input value={note} maxLength={500} placeholder="Note (optional)" onChange={(e) => setNote(e.target.value)} aria-label="Feedback note" />
      {DECISIONS.map(([value, text]) => <Button key={value} size="sm" variant={current?.decision === value ? 'primary' : 'secondary'} disabled={busy !== null} onClick={() => send(value)}>{busy === value ? '…' : text}</Button>)}
    </div> : <p className="muted">Sign in as an operator to record a decision.</p>}
    {error && <p className="form-error">{error}</p>}
  </div>
}

function RecommendationCard({ rec, isOperator, aiReady, onAnalyze, analyzing, onSaved }) {
  const savings = rec.estimated_savings
  const v = rec.validation || {}
  return <article className="panel rec-card">
    <header className="rec-head">
      <div className="rec-badges">
        <Badge tone={severityTone(rec.severity)}>{rec.severity}</Badge>
        <Badge tone={stateTone(rec.evidence_state)}>{label(rec.evidence_state)}</Badge>
        <Badge tone="neutral">{label(rec.category)}</Badge>
        <Badge tone={rec.generator === 'llm' ? 'brand' : 'neutral'}>{rec.generator === 'llm' ? 'AI-written, validated' : 'Rule template'}</Badge>
        {rec.finding_status && rec.finding_status !== 'open' && <Badge tone="info">{label(rec.finding_status)}</Badge>}
      </div>
      <span className="rec-priority" title="Deterministic priority score (0-100)">Priority <strong>{rec.priority_score}</strong></span>
    </header>
    <div className="rec-grid">
      <Field n="1" title="Title"><p><strong>{rec.title}</strong></p></Field>
      <Field n="2" title="Affected resource"><p><span className="sub">{rec.resource.type}{rec.resource.region ? ` · ${rec.resource.region}` : ''}</span><span className="resource-id">{rec.resource.id}</span></p></Field>
      <Field n="3" title="Problem"><p>{rec.problem}</p></Field>
      <Field n="4" title="Evidence"><ul className="evidence-list">{rec.evidence.map((e) => <li key={e.evidence_id}><code>{e.source}</code> {e.observation}</li>)}</ul></Field>
      <Field n="5" title="Why it matters"><p>{rec.why_it_matters}</p></Field>
      <Field n="6" title="Suggested action"><p>{rec.suggested_action}</p>{rec.remediation_steps?.length > 0 && <ol>{rec.remediation_steps.map((s) => <li key={s}>{s}</li>)}</ol>}</Field>
      <Field n="7" title="Expected benefits"><List items={rec.expected_benefits} /></Field>
      <Field n="8" title="Potential risks"><List items={rec.potential_risks} /></Field>
      <Field n="9" title="Estimated savings">{savings.validated ? <p><strong>${savings.amount_usd_per_month.toFixed(2)} / month</strong> <span className="muted">{savings.basis}</span></p> : <p className="muted">{savings.basis}</p>}</Field>
      <Field n="10" title="Confidence"><p>{label(rec.confidence)}</p></Field>
      <Field n="11" title="Missing information"><List items={rec.missing_information} empty="Nothing identified." /></Field>
      <Field n="12" title="Human approval"><p><ShieldAlert size={13} /> Required. CloudOps AI does not make this change.</p></Field>
    </div>
    {rec.correlation_note && <p className="rec-correlation"><Lightbulb size={14} /> {rec.correlation_note}</p>}
    {v.checked === 'llm' && !v.passed && <div className="rec-violations"><strong>AI text was rejected, so the rule template is shown.</strong>{v.provider_error ? <p>{v.provider_error}</p> : <ul>{(v.violations || []).map((x) => <li key={x}>{x}</li>)}</ul>}</div>}
    <footer className="rec-foot">
      <Feedback rec={rec} isOperator={isOperator} onSaved={onSaved} />
      {isOperator && aiReady && rec.generator !== 'llm' && <Button size="sm" variant="ghost" disabled={analyzing} onClick={() => onAnalyze([rec.finding_id])}><Sparkles size={14} /> Rewrite with AI</Button>}
    </footer>
  </article>
}

function Recommendations({ isOperator, onSignIn, sessionKey }) {
  const [data, setData] = useState(null)
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [severity, setSeverity] = useState('')

  const load = useCallback(async (refresh = false) => {
    setLoading(true); setError(null)
    try {
      const [recs, st] = await Promise.all([getAiRecommendations(refresh), getAiStatus()])
      setData(recs.data); setStatus(st.data)
    } catch (err) { setError(describeError(err)); setData(null) } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => load(false), 0)
    return () => window.clearTimeout(timer)
  }, [load, sessionKey])

  const analyze = async (findingIds) => {
    setAnalyzing(true); setAnalysis(null)
    try {
      const { data: result } = await analyzeWithAi(findingIds ? { finding_ids: findingIds, limit: findingIds.length } : { limit: 5 })
      setAnalysis({ ok: true, result })
      await load(false)
    } catch (err) { setAnalysis({ ok: false, message: describeError(err).message }) } finally { setAnalyzing(false) }
  }

  const provider = status?.provider
  const aiReady = Boolean(provider && provider.provider !== 'none')
  const recs = (data?.recommendations || []).filter((r) => !severity || r.severity === severity)
  const remaining = status && status.calls_used_today != null ? Math.max(0, status.daily_call_limit - status.calls_used_today) : null

  return <main className="dashboard-content">
    <div className="page-heading"><div><span className="eyebrow">Rules detect, AI explains</span><h1>Recommendations</h1><p>Each finding becomes a recommendation with evidence, trade-offs and missing information. Every action needs human approval.</p></div>
      <div className="heading-actions"><button className="secondary-button" onClick={() => load(true)} disabled={loading} title="Re-scan sources"><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button></div></div>
    {error ? <AccessGate error={error} onSignIn={onSignIn} /> : <>
      <div className="two-column rec-top">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Posture summary</span><h2>Where things stand</h2><p>Counts of real findings only.</p></div><Lightbulb className="panel-heading-icon" size={20} /></div>
          {loading && !data ? <EmptyState loading /> : <p className="posture-text">{data?.summary?.text}</p>}
          <SourceStatus sources={data?.sources} />
          {data && !data.persisted && <p className="muted">Not saved: no database is configured, so feedback and AI rewrites are unavailable.</p>}
        </section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Optional</span><h2>AI rewrite</h2><p>Runs only when you ask. Output is checked against the evidence and rejected if it invents anything.</p></div><Bot className="panel-heading-icon" size={20} /></div>
          {status && <dl className="ai-status">
            <div><dt>Provider</dt><dd>{aiReady ? `${label(provider.provider)} · ${provider.model}` : 'None configured'}</dd></div>
            <div><dt>Calls today</dt><dd>{status.calls_used_today ?? '—'} of {status.daily_call_limit}</dd></div>
          </dl>}
          {!aiReady && status && <p className="muted">Recommendations work fully without AI. To enable rewrites, set CLOUDOPS_AI_PROVIDER on the API (ollama for a free local model).</p>}
          {isOperator && aiReady && <Button variant="primary" disabled={analyzing || remaining === 0} onClick={() => analyze(null)}><Sparkles size={15} /> {analyzing ? 'Analyzing…' : 'Rewrite top 5 with AI'}</Button>}
          {!isOperator && aiReady && <p className="muted">Sign in as an operator to run an AI rewrite.</p>}
          {analysis && (analysis.ok ? <ul className="analysis-result">{analysis.result.results.map((r) => <li key={r.finding_id}>{OUTCOMES[r.outcome] || r.outcome}</li>)}<li className="muted">{analysis.result.provider_calls} provider call(s) used.</li></ul> : <p className="form-error">{analysis.message}</p>)}
        </section>
      </div>
      <div className="table-toolbar filters-row">
        <label className="filter-select"><span>Severity</span><select value={severity} onChange={(e) => setSeverity(e.target.value)}><option value="">All severities</option>{SEVERITIES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select></label>
        <span className="muted">{recs.length} recommendation(s), highest priority first</span>
      </div>
      {loading && !data ? <div className="panel"><EmptyState loading /></div>
        : recs.length === 0 ? <div className="panel"><EmptyState title="No recommendations" description="No open findings in the sources that could be scanned." /></div>
        : <div className="rec-list">{recs.map((r) => <RecommendationCard key={r.recommendation_id} rec={r} isOperator={isOperator} aiReady={aiReady && remaining !== 0} onAnalyze={analyze} analyzing={analyzing} onSaved={() => load(false)} />)}</div>}
    </>}
  </main>
}

export default Recommendations
