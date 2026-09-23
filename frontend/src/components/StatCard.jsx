import { ArrowUpRight, BarChart3, Boxes, Lightbulb, Wallet } from 'lucide-react'

const icons = { resources: Boxes, cost: Wallet, savings: ArrowUpRight, recommendations: Lightbulb }

function StatCard({ label, kind, description, loading = false, value = null }) {
  const Icon = icons[kind] || BarChart3
  return <article className="stat-card">
    <div className="stat-card-top"><span>{label}</span><div className="stat-icon"><Icon size={18} /></div></div>
    <div className={`stat-value ${loading ? 'skeleton' : ''}`}>{loading ? '' : value || '--'}</div>
    <p>{description}</p>
  </article>
}

export default StatCard
