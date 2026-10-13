import { Skeleton } from '@/components/ui/skeleton'

// Measurement register cell: a KPI card — a label, a tabular measurement, and
// an honest em dash for anything unmeasured.
function RegisterCell({ label, value, unmeasured = false, note, loading = false }) {
  return (
    <div className="border-border bg-card flex flex-col gap-1 rounded-2xl border p-5">
      <span className="text-muted-foreground text-xs font-medium">{label}</span>
      {loading
        ? <Skeleton className="h-8 w-24" />
        : <span className={`text-2xl font-semibold tracking-tight tabular-nums ${unmeasured ? 'text-muted-foreground' : 'text-foreground'}`}>{value}</span>}
      {note && <span className="text-muted-foreground text-xs">{note}</span>}
    </div>
  )
}

export default RegisterCell
