import { Inbox, LoaderCircle } from 'lucide-react'

function EmptyState({ title = 'No data available', description, loading = false, error = false }) {
  return (
    <div className={`empty-state ${loading ? 'is-loading' : ''} ${error ? 'is-error' : ''}`}>
      {loading ? <LoaderCircle className="empty-icon spin" size={22} /> : <Inbox className="empty-icon" size={22} />}
      <strong>{loading ? 'Loading data…' : error ? 'Unable to load data' : title}</strong>
      {description && <p>{description}</p>}
    </div>
  )
}

export default EmptyState
