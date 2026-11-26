import { BarChart3, Bot, Boxes, Cloud, Cog, FileCode2, LayoutDashboard, Lightbulb, ShieldCheck, X } from 'lucide-react'
import StatusPill from './ui/StatusPill'

const navigation = [
  ['Overview', LayoutDashboard],
  ['Resources', Boxes],
  ['Cost Analysis', BarChart3],
  ['AI Insights', Bot],
  ['IaC Review', FileCode2],
  ['Governance', ShieldCheck],
  ['Recommendations', Lightbulb],
  ['Settings', Cog],
]

function Sidebar({ activePage, onNavigate, open, onClose }) {
  return (
    <aside className={`sidebar ${open ? 'is-open' : ''}`}>
      <div className="brand-row">
        <div className="brand-mark"><Cloud size={18} /></div>
        <div><strong>CloudOps AI</strong><span>Cloud Intelligence Platform</span></div>
        <button type="button" className="icon-button mobile-close" onClick={onClose} aria-label="Close navigation"><X size={18} /></button>
      </div>
      <nav aria-label="Primary navigation">
        <p className="nav-label">Workspace</p>
        {navigation.map(([label, Icon]) => (
          <button
            key={label}
            type="button"
            className={`nav-item ${activePage === label ? 'active' : ''}`}
            onClick={() => onNavigate(label)}
            aria-current={activePage === label ? 'page' : undefined}
          >
            <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer"><StatusPill tone="neutral" title="CloudOps AI only reads AWS data and never changes infrastructure">Read-only access</StatusPill></div>
    </aside>
  )
}

export default Sidebar
