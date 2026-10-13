import { AlertTriangle, Bot, CircleDollarSign, RefreshCw, Tags } from 'lucide-react'
import { useEffect, useState } from 'react'
import ChartBoard from '../components/ChartBoard'
import EmptyState from '../components/EmptyState'
import RegisterCell from '../components/RegisterCell'
import ResourceTable from '../components/ResourceTable'
import { getCostForecast, getCosts, getEc2Metrics, getEc2Resources, getInsights, getOverview } from '../services/api'
import { sample } from '../services/sampleData'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

const DASH = '—'
const formatCurrency = (value, currency = 'USD') => typeof value === 'number' ? new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value) : DASH
const getPayload = (result) => result.status === 'fulfilled' ? result.value.data : null
const isSampleMode = () => new URLSearchParams(window.location.search).get('sample') !== '0'

function useDashboardData() {
  const [data, setData] = useState({ overview: null, resources: null, metrics: null, costs: null, insights: null, dailyCosts: null, forecast: null })
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const load = async () => {
    if (isSampleMode()) {
      setData(sample)
      setLastUpdated(new Date())
      setLoading(false)
      return
    }
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

function DataStatus({ data, loading, lastUpdated, sampleMode = false }) {
  if (sampleMode) return null
  const connected = Object.values(data).some((item) => item?.status === 'ok' || item?.status === 'healthy')
  const state = loading ? 'loading' : connected ? 'live' : 'offline'
  const label = { loading: 'Loading measurements', live: `Live data${lastUpdated ? ` · ${lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}`, offline: 'Backend data unavailable' }[state]
  const tone = state === 'live' ? 'bg-success-background text-success' : state === 'offline' ? 'bg-warning-background text-warning' : 'bg-muted text-muted-foreground'
  return <Badge variant="outline" className={`h-6 gap-1.5 rounded-full border-transparent px-2.5 ${tone}`}><i className="size-1.5 rounded-full bg-current" /> {label}</Badge>
}

function Panel({ title, description, icon, children, className = '', boxed = false, bordered = true }) {
  if (boxed) {
    return (
      <section className={`border-border bg-card flex min-w-0 flex-col gap-4 rounded-2xl border p-6 ${className}`}>
        {(title || description || icon) && (
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              {title && <h2 className="text-base font-semibold">{title}</h2>}
              {description && <p className="text-muted-foreground text-sm">{description}</p>}
            </div>
            {icon}
          </div>
        )}
        {children}
      </section>
    )
  }
  return (
    <section className={`min-w-0 ${bordered ? 'border-border border-t pt-6' : ''} ${className}`}>
      {(title || description || icon) && (
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="space-y-1">
            {title && <h2 className="text-base font-semibold">{title}</h2>}
            {description && <p className="text-muted-foreground text-sm">{description}</p>}
          </div>
          {icon}
        </div>
      )}
      {children}
    </section>
  )
}

function PlotEmpty({ title, description, minHeight = 180 }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-6 py-8 text-center" style={{ minHeight }}>
      <strong className="text-sm font-medium">{title}</strong>
      <p className="text-muted-foreground max-w-[46ch] text-sm leading-relaxed">{description}</p>
    </div>
  )
}

function PageHeading({ title, intro, badge, actions }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {badge}
        </div>
        {intro && <p className="text-muted-foreground text-sm">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

function CostPanel({ costs, dailyCosts, forecast, loading, period = 'monthly', boxed = false }) {
  const services = costs?.services || []
  const unavailable = costs?.status === 'unavailable' || !costs
  const range = costs?.start && costs?.end_inclusive ? `${costs.start} → ${costs.end_inclusive}` : period === 'monthly' ? 'Current billing period' : 'Rolling 30 days'
  const figures = [
    ...services.slice(0, 6).map((item) => [item.service, formatCurrency(item.cost, costs.currency)]),
    ...(period === 'monthly' ? [['Last 30 days', formatCurrency(dailyCosts?.total_cost, dailyCosts?.currency)], ['Month-end forecast (AWS)', forecast?.available ? formatCurrency(forecast.mean, forecast.currency) : DASH]] : []),
  ]
  return (
    <Panel
      boxed={boxed}
      title="Cost overview"
      description={<>{period === 'monthly' ? 'Cost Explorer, month to date' : 'Cost Explorer, rolling 30 days'}. <span className="font-mono">{range}</span></>}
      icon={<CircleDollarSign className="text-muted-foreground size-5" strokeWidth={1.8} />}
    >
      {loading ? <EmptyState loading title="Loading cost data" /> : unavailable ? (
        <PlotEmpty title="No measurements recorded" description="Cost Explorer data requires valid AWS access and permissions. The figure stays empty until it can be measured." />
      ) : services.length ? (
        <>
          <ChartBoard
            series={services.map((item) => ({ label: item.service, label_full: item.service, value: item.cost }))}
            currency={costs.currency}
            caption={`Cost by service · ${costs.currency || 'USD'}`}
            note={`${services.length} services measured`}
          />
          <dl className="divide-border mt-4 flex flex-col divide-y">
            {figures.map(([key, value]) => (
              <div className="flex items-baseline justify-between gap-3 py-2.5 text-sm" key={key}>
                <dt className="text-muted-foreground min-w-0 truncate">{key}</dt>
                <dd className="font-mono font-semibold tabular-nums whitespace-nowrap">{value}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        <PlotEmpty title="No measurements recorded" description="Cost Explorer returned no grouped services for this period." />
      )}
    </Panel>
  )
}

const SEVERITY_TEXT = { high: 'text-destructive', medium: 'text-warning', low: 'text-muted-foreground' }
const SEVERITY_WORD = { high: 'High', medium: 'Medium', low: 'Low' }

function FindingRow({ finding, expanded, onToggle }) {
  const severity = finding.severity || 'unclassified'
  const savings = finding.estimated_monthly_savings
  const spec = [
    ['Action', finding.recommendation || DASH],
    ['Monthly saving', typeof savings === 'number' && savings > 0 ? formatCurrency(savings) : DASH],
    ['Resource', `${finding.resource_id || DASH}${finding.resource_type ? ` · ${finding.resource_type}` : ''}`],
  ]
  return (
    <div className="border-border border-b last:border-b-0">
      <div className="flex items-start gap-3 py-3">
        <span className={`mt-1.5 size-2 shrink-0 rounded-full ${severity === 'high' ? 'bg-destructive' : severity === 'medium' ? 'bg-warning' : 'bg-muted-foreground'}`} aria-hidden="true" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium break-words">
            {finding.issue || 'Finding'}
            <span className={`text-xs font-semibold ${SEVERITY_TEXT[severity] || SEVERITY_TEXT.low}`}>{SEVERITY_WORD[severity] || severity}</span>
          </span>
          <span className="text-muted-foreground font-mono text-xs">{finding.resource_id || 'Resource unavailable'}</span>
        </div>
        <span className="font-mono text-sm font-semibold tabular-nums" title={savings > 0 ? 'Estimated monthly saving reported by the finding' : 'No saving reported'}>
          {typeof savings === 'number' && savings > 0 ? formatCurrency(savings) : DASH}
        </span>
        <Button variant="link" size="sm" className="h-auto p-0" aria-expanded={expanded} onClick={onToggle}>{expanded ? 'Hide' : 'Review'}</Button>
      </div>
      {expanded && (
        <div className="pb-4 pl-5">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            {spec.map(([key, val], i) => (
              <div key={key} className="grid grid-cols-[120px_1fr] gap-3">
                <dt className="text-muted-foreground text-xs font-medium">{key}</dt>
                <dd className={`text-sm ${i > 0 ? 'font-mono tabular-nums' : ''}`}>{val}</dd>
              </div>
            ))}
            {finding.evidence?.length ? (
              <div className="grid grid-cols-[120px_1fr] gap-3 sm:col-span-2">
                <dt className="text-muted-foreground text-xs font-medium">Evidence</dt>
                <dd className="text-sm"><ul className="list-disc space-y-0.5 pl-4">{finding.evidence.map((line, i) => <li key={i}>{line}</li>)}</ul></dd>
              </div>
            ) : null}
          </dl>
        </div>
      )}
    </div>
  )
}

function FindingsPanel({ findings, loading, fullPage = false }) {
  const [openKey, setOpenKey] = useState(null)
  const shown = fullPage ? findings : findings.slice(0, 5)
  return (
    <Panel
      boxed
      title="Optimization findings"
      description="Rules detect, then explain. Every finding is read-only and waits for human review."
      icon={<AlertTriangle className="text-muted-foreground size-5" strokeWidth={1.8} />}
    >
      {loading ? <EmptyState loading title="Loading findings" /> : !findings.length ? (
        <PlotEmpty title="No findings recorded" description="Findings appear when the decision engine identifies a review opportunity in the measured resource state." />
      ) : (
        <>
          <div className="flex flex-col">
            {shown.map((finding, index) => {
              const key = `${finding.resource_id}-${finding.issue}-${index}`
              return <FindingRow key={key} finding={finding} expanded={openKey === key} onToggle={() => setOpenKey(openKey === key ? null : key)} />
            })}
          </div>
          {!fullPage && findings.length > shown.length && (
            <div className="border-border mt-1 border-t pt-3">
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => window.dispatchEvent(new CustomEvent('cloudops:navigate', { detail: 'AI Insights' }))}>
                Open AI Insights for all {findings.length} findings
              </Button>
            </div>
          )}
        </>
      )}
    </Panel>
  )
}

// A findings list that owns its own expand state, so every sheet's Review
// button works. The Overview queue is capped and links out; the full sheets
// use this to expand any row.
function FindingsList({ findings = [] }) {
  const [openKey, setOpenKey] = useState(null)
  return (
    <div className="flex flex-col">
      {findings.map((finding, index) => {
        const key = `${finding.resource_id}-${finding.issue}-${index}`
        return <FindingRow key={key} finding={finding} expanded={openKey === key} onToggle={() => setOpenKey(openKey === key ? null : key)} />
      })}
    </div>
  )
}

// The review record for one Terraform plan. No plan is ever submitted from
// here (read-only), so every field is an em dash with the reason beside it,
// per the honesty rule.
function IacSection() {
  const fields = [
    { label: 'Plan received', note: 'No plan submitted yet' },
    { label: 'Resources changed', note: 'Awaits a plan' },
    { label: 'Monthly cost delta', note: 'Awaits Infracost output' },
    { label: 'Metrics', note: 'Awaits a plan' },
    { label: 'Policy findings', note: 'Awaits a plan' },
    { label: 'Review status', note: 'Awaits human review' },
  ]
  return (
    <Panel bordered={false}>
      <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
        {fields.map((field) => (
          <div className="flex flex-col gap-1" key={field.label}>
            <dt className="text-muted-foreground text-xs font-medium">{field.label}</dt>
            <dd className="flex items-baseline gap-2">
              <span className="font-mono text-sm font-semibold tabular-nums">{DASH}</span>
              <span className="text-muted-foreground text-xs">{field.note}</span>
            </dd>
          </div>
        ))}
      </dl>
    </Panel>
  )
}

const TITLES = {
  Overview: 'Infrastructure overview',
  Resources: 'Resource inventory',
  'Cost Analysis': 'Cost analysis',
  'AI Insights': 'AI insights',
  'IaC Review': 'Infrastructure as Code review',
  Governance: 'Governance signals',
  Settings: 'Connection settings',
}

const INTROS = {
  Overview: "Here's how your AWS account is doing. Unavailable measurements stay marked, never filled in.",
  Resources: 'The read-only EC2 inventory, with ownership and utilization where they were measured.',
  'Cost Analysis': 'Cost Explorer measurements for the account: spend to date, the rolling 30 days, and the AWS forecast.',
  'AI Insights': 'Rules detect findings. The explanation layer adds context and trade-offs for human review.',
  'IaC Review': 'Submit a Terraform plan and Infracost output for read-only, cost-aware review.',
  Governance: 'Policy and ownership findings, shown when the configured analysis returns them.',
  Settings: 'How this frontend reaches the backend, and where credentials stay.',
}

function CostAnalysis({ data, loading }) {
  const [period, setPeriod] = useState('monthly')
  const costs = period === 'monthly' ? data.costs : data.dailyCosts
  return (
    <>
      <Tabs value={period} onValueChange={setPeriod}>
        <TabsList>
          <TabsTrigger value="monthly">Month to date</TabsTrigger>
          <TabsTrigger value="daily">Last 30 days</TabsTrigger>
        </TabsList>
      </Tabs>
      <section aria-label="Cost register" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <RegisterCell label="Period total" value={formatCurrency(costs?.total_cost, costs?.currency)} unmeasured={costs?.total_cost == null} note={costs?.start && costs?.end_inclusive ? `${costs.start} → ${costs.end_inclusive}` : 'Cost Explorer'} loading={loading} />
        <RegisterCell label="Services measured" value={costs?.services?.length == null ? DASH : String(costs.services.length)} unmeasured={!costs?.services?.length} note="Grouped by AWS service" loading={loading} />
        <RegisterCell label="Largest service" value={costs?.services?.[0] ? formatCurrency(costs.services[0].cost, costs.currency) : DASH} unmeasured={!costs?.services?.[0]} note={costs?.services?.[0]?.service || 'No service costs returned'} loading={loading} />
        <RegisterCell label="Month-end forecast" value={data.forecast?.available ? formatCurrency(data.forecast.mean, data.forecast.currency) : DASH} unmeasured={!data.forecast?.available} note="AWS GetCostForecast" loading={loading} />
      </section>
      <CostPanel costs={costs} dailyCosts={data.dailyCosts} forecast={data.forecast} loading={loading} period={period} />
    </>
  )
}

function Dashboard({ activePage = 'Overview', sampleMode = false }) {
  const { data, loading, lastUpdated, reload } = useDashboardData()
  const resources = data.resources?.instances || []
  const findings = data.insights?.findings || []
  const savings = findings.reduce((total, finding) => total + (typeof finding.estimated_monthly_savings === 'number' ? finding.estimated_monthly_savings : 0), 0)

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-6 p-4 md:p-6 lg:p-8">
      {activePage === 'Overview' && (
        <PageHeading
          title={TITLES.Overview}
          intro={INTROS.Overview}
          badge={<DataStatus data={data} loading={loading} lastUpdated={lastUpdated} sampleMode={sampleMode} />}
          actions={(
            <Button variant="secondary" size="sm" className="text-xs" onClick={reload} disabled={loading} title="Refresh backend data">
              <RefreshCw className={loading ? 'size-3.5 animate-spin' : 'size-3.5'} /> Refresh
            </Button>
          )}
        />
      )}

      {activePage === 'Overview' && (
        <>
          <section aria-label="Measurement register" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <RegisterCell label="Monthly cloud cost" value={formatCurrency(data.costs?.total_cost, data.costs?.currency)} unmeasured={data.costs?.total_cost == null} note="Cost Explorer, month to date" loading={loading} />
            <RegisterCell label="Resources" value={data.resources?.total_instances == null ? DASH : String(data.resources.total_instances)} unmeasured={data.resources?.total_instances == null} note="EC2 instances discovered" loading={loading} />
            <RegisterCell label="Potential savings" value={savings > 0 ? formatCurrency(savings, data.costs?.currency) : DASH} unmeasured={!(savings > 0)} note="Only where a finding reports it" loading={loading} />
            <RegisterCell label="Active findings" value={data.insights?.total_findings == null ? DASH : String(data.insights.total_findings)} unmeasured={data.insights?.total_findings == null} note="Deterministic decision engine" loading={loading} />
          </section>
          <div className="grid gap-6 lg:grid-cols-2">
            <CostPanel costs={data.costs} dailyCosts={data.dailyCosts} forecast={data.forecast} loading={loading} boxed />
            <FindingsPanel findings={findings} loading={loading} />
          </div>
          <ResourceTable resources={resources} metrics={data.metrics?.metrics || []} loading={loading} />
          <IacSection />
        </>
      )}

      {activePage === 'Resources' && (
        <>
          <PageHeading title={TITLES.Resources} intro={INTROS.Resources} badge={<DataStatus data={data} loading={loading} lastUpdated={lastUpdated} sampleMode={sampleMode} />} />
          <ResourceTable resources={resources} metrics={data.metrics?.metrics || []} loading={loading} fullPage />
        </>
      )}

      {activePage === 'Cost Analysis' && <CostAnalysis data={data} loading={loading} />}

      {activePage === 'AI Insights' && (
        <div className="flex flex-col gap-3">
          <PageHeading title={TITLES['AI Insights']} />
          <Panel
            bordered={false}
            description={data.insights?.explanation || 'Detection runs on deterministic rules; the explanation layer adds context and trade-offs.'}
            icon={<Bot className="text-muted-foreground size-5" strokeWidth={1.8} />}
          >
            {loading ? <EmptyState loading title="Loading findings" /> : !findings.length ? (
              <PlotEmpty title="No findings recorded" description="Findings appear when the decision engine identifies a review opportunity in the measured resource state." />
            ) : (
              <FindingsList findings={findings} />
            )}
          </Panel>
        </div>
      )}

      {activePage === 'IaC Review' && (
        <>
          <PageHeading title={TITLES['IaC Review']} intro={INTROS['IaC Review']} />
          <IacSection />
          <Panel title="Plan analysis" description={<>Submit a plan with <span className="font-mono">POST /api/iac/analyze</span> to review proposed infrastructure changes.</>}>
            <PlotEmpty title="No plan submitted" description="A Terraform plan and Infracost output can be analyzed read-only. Nothing is applied, and the review record stays empty until a plan arrives." />
          </Panel>
        </>
      )}

      {activePage === 'Governance' && (
        <>
          <PageHeading title={TITLES.Governance} intro={INTROS.Governance} />
          <Panel
            title="Governance signals"
            description="Findings the analysis tags as policy or ownership issues."
            icon={<Tags className="text-muted-foreground size-5" strokeWidth={1.8} />}
          >
            {loading ? <EmptyState loading title="Loading findings" /> : (() => {
              const governance = findings.filter((finding) => /tag|policy|owner/i.test(finding.issue || ''))
              return governance.length ? (
                <FindingsList findings={governance} />
              ) : (
                <PlotEmpty title="No findings recorded" description="Governance findings appear when a resource is missing ownership or policy tags." />
              )
            })()}
          </Panel>
        </>
      )}

      {activePage === 'Settings' && (
        <>
          <PageHeading title={TITLES.Settings} intro={INTROS.Settings} />
          <Panel
            title="Connection settings"
            description={<>Frontend requests use <span className="font-mono">VITE_API_URL</span>. Backend credentials remain in the standard AWS credential chain and are never exposed to the browser.</>}
            className="max-w-3xl"
          >
            <dl className="flex flex-col">
              {[
                ['API base URL', import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'],
                ['Infrastructure actions', 'Read-only. Terraform apply is not exposed.'],
                ['Sample mode', <>On by default, from <span className="font-mono">src/services/sampleData.js</span>. Append <span className="font-mono">?sample=0</span> to reach a live backend instead.</>],
              ].map(([key, val], i) => (
                <div key={key}>
                  {i > 0 && <Separator />}
                  <div className="grid grid-cols-[180px_1fr] gap-4 py-3">
                    <dt className="text-muted-foreground text-sm font-medium">{key}</dt>
                    <dd className="text-sm">{val}</dd>
                  </div>
                </div>
              ))}
            </dl>
          </Panel>
        </>
      )}
    </div>
  )
}

export default Dashboard
