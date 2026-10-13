import { useMemo, useState } from 'react'
import { ArrowDownUp, Search } from 'lucide-react'
import EmptyState from './EmptyState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const DASH = '—'
const STATE_TONE = { running: 'text-success', stopped: 'text-warning' }

function UtilCell({ metric }) {
  if (metric?.cpu_average == null) return <TableCell className="text-muted-foreground">{DASH}</TableCell>
  const value = Number(metric.cpu_average)
  return (
    <TableCell>
      <span className="flex items-center gap-2">
        <span className="bg-muted h-1 w-11 overflow-hidden rounded-full"><span className="bg-chart-3 block h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></span>
        <span className="text-muted-foreground text-xs tabular-nums">{value}%</span>
      </span>
    </TableCell>
  )
}

function ResourceRow({ resource, metric }) {
  const [open, setOpen] = useState(false)
  const tags = resource.tags || {}
  const launch = resource.launch_time ? new Date(resource.launch_time) : null
  const spec = [
    ['Launched', launch ? launch.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : DASH],
    ['CPU average', metric?.cpu_average != null ? `${metric.cpu_average}% (${metric.data_points} points, 24h)` : DASH],
    ['CPU peak', metric?.cpu_max != null ? `${metric.cpu_max}%` : DASH],
    ['Tags', Object.keys(tags).length ? Object.entries(tags).map(([k, v]) => `${k}=${v}`).join(', ') : 'None reported'],
  ]
  return (
    <>
      <TableRow>
        <TableCell><strong className="font-mono text-xs font-medium">{resource.instance_id || DASH}</strong></TableCell>
        <TableCell>{resource.instance_type || DASH}</TableCell>
        <TableCell>
          <span className={`inline-flex items-center gap-1.5 text-sm ${STATE_TONE[resource.state] || 'text-muted-foreground'}`}><i className="size-1.5 rounded-full bg-current" aria-hidden="true" />{resource.state || 'unknown'}</span>
        </TableCell>
        <TableCell>{resource.availability_zone || DASH}</TableCell>
        <TableCell>{tags.Environment || tags.environment || 'Unassigned'}</TableCell>
        <TableCell>{tags.Owner || tags.owner || 'Unassigned'}</TableCell>
        <UtilCell metric={metric} />
        <TableCell className="text-right">
          <Button variant="link" size="sm" className="h-auto p-0" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Details'}</Button>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={8}>
            <dl className="grid gap-x-6 gap-y-3 py-1 sm:grid-cols-2">
              {spec.map(([key, val], i) => (
                <div key={key} className="grid grid-cols-[140px_1fr] gap-3">
                  <dt className="text-muted-foreground text-xs font-medium">{key}</dt>
                  <dd className={`text-sm ${i < 3 ? 'font-mono tabular-nums' : ''}`}>{val}</dd>
                </div>
              ))}
            </dl>
          </TableCell>
        </TableRow>
      )}
    </>
  )
}

function ResourceTable({ resources = [], metrics = [], loading = false, fullPage = false }) {
  const [query, setQuery] = useState('')
  const [stateFilter, setStateFilter] = useState('all')
  const [newestFirst, setNewestFirst] = useState(true)

  const metricsById = useMemo(() => Object.fromEntries(metrics.map((m) => [m.instance_id, m])), [metrics])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return resources
      .filter((r) => (stateFilter === 'all' ? true : (r.state || 'unknown') === stateFilter))
      .filter((r) => !q || [r.instance_id, r.instance_type, r.availability_zone, JSON.stringify(r.tags || {})].join(' ').toLowerCase().includes(q))
      .sort((a, b) => {
        const ta = a.launch_time ? new Date(a.launch_time).getTime() : 0
        const tb = b.launch_time ? new Date(b.launch_time).getTime() : 0
        return newestFirst ? tb - ta : ta - tb
      })
  }, [resources, query, stateFilter, newestFirst])

  const states = useMemo(() => {
    const counts = {}
    for (const r of resources) counts[r.state || 'unknown'] = (counts[r.state || 'unknown'] || 0) + 1
    return counts
  }, [resources])

  return (
    <section className={fullPage ? 'flex-1' : ''}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden="true" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search id, type, tag" aria-label="Search resources" className="bg-transparent pl-9" />
          </div>
          <Button variant="ghost" size="sm" className="ml-auto text-xs" onClick={() => setNewestFirst(!newestFirst)}>
            <ArrowDownUp className="size-3.5" /> {newestFirst ? 'Newest first' : 'Oldest first'}
          </Button>
          {['all', 'running', 'stopped'].map((s) => (
            <Button key={s} variant={stateFilter === s ? 'default' : 'ghost'} size="sm" className="text-xs" onClick={() => setStateFilter(s)}>
              {s === 'all' ? 'All' : s[0].toUpperCase() + s.slice(1)} ({s === 'all' ? resources.length : states[s] || 0})
            </Button>
          ))}
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Resource ID</TableHead><TableHead>Type</TableHead><TableHead>State</TableHead><TableHead>Availability zone</TableHead><TableHead>Environment</TableHead><TableHead>Owner</TableHead><TableHead>Utilization 24h</TableHead><TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={8}><EmptyState loading title="Loading resources" /></TableCell></TableRow>
            ) : filtered.length ? (
              filtered.map((resource) => <ResourceRow key={resource.instance_id} resource={resource} metric={metricsById[resource.instance_id]} />)
            ) : (
              <TableRow><TableCell colSpan={8}><EmptyState title={query || stateFilter !== 'all' ? 'No resources match the current filter' : 'No AWS resources discovered'} description={query || stateFilter !== 'all' ? 'Clear the search or state filter to see the full inventory.' : 'Connect AWS read access and add a scan to populate this sheet.'} /></TableCell></TableRow>
            )}
          </TableBody>
        </Table>

        <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 text-xs">
          <span>Showing {filtered.length} of {resources.length} resources</span>
          <span>{metrics.length ? 'Utilization from CloudWatch, last 24h' : 'Utilization unavailable'}</span>
        </div>
      </div>
    </section>
  )
}

export default ResourceTable
