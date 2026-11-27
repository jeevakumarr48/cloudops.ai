import { FlaskConical, X } from 'lucide-react'
import { useDemo } from '../demo/demoMode'

function DemoBanner() {
  const { demo, exitDemo } = useDemo()
  if (!demo) return null
  return <div className="demo-banner" role="status">
    <FlaskConical size={16} />
    <span><strong>Demo</strong> · Sample data, not a real AWS account. The resources are synthetic inputs run through the real rules. Nothing can be changed.</span>
    <button type="button" className="plain-icon-button" onClick={exitDemo}><X size={15} /> Exit demo</button>
  </div>
}

export default DemoBanner
