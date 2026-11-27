import { FlaskConical, Lightbulb, ShieldCheck } from 'lucide-react'
import Button from '../components/ui/Button'

// Shown in demo mode for pages that only work with a live AWS connection.
function DemoNotice({ page, onNavigate }) {
  return <main className="dashboard-content">
    <div className="panel access-gate demo-notice">
      <FlaskConical size={22} />
      <strong>{page} uses live AWS data</strong>
      <p>This page reads the connected AWS account directly, so it has no sample version. The demo covers the governance engine and its recommendations.</p>
      <div className="demo-notice-actions">
        <Button variant="primary" onClick={() => onNavigate('Governance')}><ShieldCheck size={15} /> Governance findings</Button>
        <Button variant="secondary" onClick={() => onNavigate('Recommendations')}><Lightbulb size={15} /> Recommendations</Button>
      </div>
    </div>
  </main>
}

export default DemoNotice
