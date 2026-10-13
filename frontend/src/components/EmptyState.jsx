import { Inbox, LoaderCircle } from 'lucide-react'

// Standard sheet-empty state. Plot surfaces use their own dashed frame
// ("NO MEASUREMENTS RECORDED"), rendered by the panel that owns them.
function EmptyState({ title = 'No data available', description, loading = false, error = false }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 px-6 py-10 text-center">
      {loading
        ? <LoaderCircle className="text-muted-foreground size-5 animate-spin" aria-hidden="true" />
        : <Inbox className="text-muted-foreground size-5" aria-hidden="true" />}
      <strong className="text-sm font-medium">{loading ? 'Loading measurements…' : error ? 'Unable to load data' : title}</strong>
      {description && <p className="text-muted-foreground max-w-[46ch] text-sm leading-relaxed">{description}</p>}
    </div>
  )
}

export default EmptyState
