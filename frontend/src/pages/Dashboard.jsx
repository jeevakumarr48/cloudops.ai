import { AlertTriangle, Bot, CircleDollarSign, FileCode2, GitPullRequest, RefreshCw, ShieldCheck, Tags } from 'lucide-react'
import { useEffect, useState } from 'react'
import EmptyState from '../components/EmptyState'
import ResourceTable from '../components/ResourceTable'
import StatCard from '../components/StatCard'
import { getCostForecast, getCosts, getEc2Metrics, getEc2Resources, getInsights, getOverview } from '../services/api'

const emptyData = { overview: null, resources: null, metrics: null, costs: null, insights: null, dailyCosts: null, forecast: null }
const formatCurrency = (value, currency = 'USD') => typeof value === 'number' ? new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value) : 'Unavailable'
const getPayload = (result) => result.status === 'fulfilled' ? result.value.data : null

function useDashboardData() {
  const [data, setData] = useState(emptyData)
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const load = async () => {
    setLoading(true)
    const results = await Promise.allSettled([getOverview(), getEc2Resources(), getEc2Metrics(), getCosts('monthly'), getInsights(), getCosts('daily'), getCostForecast('monthly')])
    setData({ overview: getPayload(results[0]), resources: getPayload(results[1]), metrics: getPayload(results[2]), costs: getPayload(results[3]), insights: getPayload(results[4]), dailyCosts: getPayload(results[5]), forecast: getPayload(results[6]) })
    setLastUpdated(new Date())
    setLoading(false)
  }
  useEffect(() => {
    const timer = window.setTimeout(load, 0)
    return () => window.clearTimeout(timer)
  }, [])
  return { data, loading, lastUpdated, reload: load }
}

function DataStatus({ data, loading, lastUpdated }) {
  const connected = Object.values(data).some((item) => item?.status === 'ok' || item?.status === 'healthy')
  return <span className={`data-badge ${connected ? 'is-live' : ''}`}><i /> {loading ? 'Loading data' : connected ? `Live data${lastUpdated ? ` · ${lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}` : 'Backend data unavailable'}</span>
}

function FindingsList({ findings = [], loading = false }) {
  if (loading) return <EmptyState loading title="Loading findings" />
  if (!findings.length) return <EmptyState title="No active findings" description="Findings appear when the decision engine identifies a review opportunity." />
  return <div className="findings-list">{findings.slice(0, 5).map((finding, index) => <article className="finding-row" key={`${finding.resource_id}-${finding.issue}-${index}`}><span className={`severity-dot ${finding.severity || 'low'}`} /><div><strong>{finding.issue || 'Finding'}</strong><span>{finding.resource_id || 'Resource unavailable'}</span></div><span className="finding-severity">{finding.severity || 'unclassified'}</span></article>)}</div>
}

function CostSummary({ costs, dailyCosts, forecast, loading }) {
  const services = costs?.services || []
  const unavailable = costs?.status === 'unavailable' || !costs
  const trendText = dailyCosts?.total_cost != null ? formatCurrency(dailyCosts.total_cost, dailyCosts.currency) : 'Unavailable'
  const forecastText = forecast?.available ? formatCurrency(forecast.mean, forecast.currency) : 'Unavailable'
  return <section className="panel cost-summary"><div className="panel-heading"><div><span className="eyebrow">Cost Explorer</span><h2>Cost overview</h2><p>{costs?.start && costs?.end ? `${costs.start} → ${costs.end_inclusive || costs.end}` : 'Current billing period'}</p></div><CircleDollarSign className="panel-heading-icon" size={20} /></div>{loading ? <EmptyState loading title="Loading cost data" /> : unavailable ? <EmptyState title="Cost data unavailable" description="Cost Explorer data requires valid AWS access and permissions." /> : <><div className="cost-total">{formatCurrency(costs.total_cost, costs.currency)}<span>{costs.currency || 'USD'} · {costs.period || 'monthly'}</span></div><div className="service-list"><div className="service-row"><span>Last 30 days</span><strong>{trendText}</strong></div><div className="service-row"><span>Month-end forecast</span><strong>{forecastText}</strong></div></div>{services.length ? <div className="service-list">{services.slice(0, 6).map((item) => <div className="service-row" key={item.service}><span>{item.service}</span><strong>{formatCurrency(item.cost, costs.currency)}</strong></div>)}</div> : <EmptyState title="No service costs returned" description="Cost Explorer returned no grouped services for this period." />}</>}</section>
}

function IacSection() {
  return <section className="section-block"><div className="section-heading"><div><span className="eyebrow">Change governance</span><h2>Infrastructure as Code review</h2><p>Every proposed change moves through cost analysis and human review.</p></div></div><div className="iac-flow"><div><GitPullRequest size={17} /><span>Change request</span></div><b>→</b><div><FileCode2 size={17} /><span>Terraform plan</span></div><b>→</b><div><CircleDollarSign size={17} /><span>Infracost</span></div><b>→</b><div><Bot size={17} /><span>CloudOps analysis</span></div><b>→</b><div><ShieldCheck size={17} /><span>Human review</span></div></div><div className="panel iac-review-empty"><EmptyState title="No Terraform analysis in this session" description="Submit a plan with POST /api/iac/analyze to review proposed infrastructure changes. CloudOps AI never applies changes automatically." /></div></section>
}

function Dashboard({ activePage = 'Overview' }) {
  const { data, loading, lastUpdated, reload } = useDashboardData()
  const resources = data.resources?.instances || []
  const findings = data.insights?.findings || []
  const totalCost = data.costs?.total_cost
  const resourceCount = data.resources?.total_instances ?? data.overview?.resources?.total_instances
  const findingCount = data.insights?.total_findings ?? data.overview?.insights?.total_findings
  const savings = findings.reduce((total, finding) => total + (typeof finding.estimated_monthly_savings === 'number' ? finding.estimated_monthly_savings : 0), 0)
  const reportedSavings = savings > 0 ? formatCurrency(savings, data.costs?.currency) : 'Unavailable'
  const pageTitle = activePage === 'Overview' ? 'Infrastructure overview' : activePage
  const pageIntro = activePage === 'Overview' ? 'Monitor cloud resources, cost signals, and explainable optimization opportunities.' : `Review ${activePage.toLowerCase()} using live backend data and explicit availability states.`

  return <main className="dashboard-content"><div className="page-heading"><div><span className="eyebrow">CloudOps AI workspace</span><h1>{pageTitle}</h1><p>{pageIntro}</p></div><div className="heading-actions"><DataStatus data={data} loading={loading} lastUpdated={lastUpdated} /><button className="secondary-button" onClick={reload} disabled={loading} title="Refresh backend data"><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh</button></div></div>
    {activePage === 'Overview' && <><section className="stats-grid"><StatCard label="Monthly cloud cost" kind="cost" description="AWS Cost Explorer" value={formatCurrency(totalCost, data.costs?.currency)} loading={loading} /><StatCard label="Resources" kind="resources" description="EC2 resources discovered" value={resourceCount == null ? 'Unavailable' : String(resourceCount)} loading={loading} /><StatCard label="Potential savings" kind="savings" description="Only reported by findings" value={reportedSavings} loading={loading} /><StatCard label="Active findings" kind="recommendations" description="Deterministic decision engine" value={findingCount == null ? 'Unavailable' : String(findingCount)} loading={loading} /></section><div className="two-column"><CostSummary costs={data.costs} dailyCosts={data.dailyCosts} forecast={data.forecast} loading={loading} /><section className="panel"><div className="panel-heading"><div><span className="eyebrow">Decision engine</span><h2>Optimization findings</h2><p>Detected from available AWS metrics and resource state.</p></div><AlertTriangle className="panel-heading-icon" size={20} /></div><FindingsList findings={findings} loading={loading} /></section></div><section className="section-block"><div className="section-heading"><div><span className="eyebrow">Operational inventory</span><h2>Resource summary</h2><p>Read-only EC2 inventory from the configured AWS account.</p></div></div><ResourceTable resources={resources} metrics={data.metrics?.metrics || []} loading={loading} /></section><IacSection /></>}
    {activePage === 'Resources' && <ResourceTable resources={resources} metrics={data.metrics?.metrics || []} loading={loading} fullPage />}
    {activePage === 'Cost Analysis' && <CostSummary costs={data.costs} dailyCosts={data.dailyCosts} forecast={data.forecast} loading={loading} />}
    {activePage === 'AI Insights' && <section className="panel insights-page"><div className="panel-heading"><div><span className="eyebrow">Detection → explanation</span><h2>AI insights</h2><p>Rules detect findings. The explanation layer adds context and trade-offs for human review.</p></div><Bot className="panel-heading-icon" size={20} /></div><FindingsList findings={findings} loading={loading} /></section>}
    {activePage === 'IaC Review' && <IacSection />}
    {activePage === 'Governance' && <section className="panel insights-page"><div className="panel-heading"><div><span className="eyebrow">Policy posture</span><h2>Governance signals</h2><p>Governance findings are shown when the configured analysis returns them.</p></div><Tags className="panel-heading-icon" size={20} /></div><FindingsList findings={findings.filter((finding) => /tag|policy|owner/i.test(finding.issue || ''))} loading={loading} /></section>}
    {activePage === 'Settings' && <section className="panel settings-page"><span className="eyebrow">Runtime configuration</span><h2>Connection settings</h2><p>Frontend requests use <strong>VITE_API_URL</strong>. Backend credentials remain in the standard AWS credential chain and are never exposed to the browser.</p><dl><div><dt>API base URL</dt><dd>{import.meta.env.VITE_API_URL || 'Local default: http://127.0.0.1:8000'}</dd></div><div><dt>Infrastructure actions</dt><dd>Read-only. Terraform apply is not exposed.</dd></div></dl></section>}
  </main>
}

export default Dashboard
