import { FlaskConical, Lock, ShieldAlert } from 'lucide-react'
import Button from '../ui/Button'
import EmptyState from '../EmptyState'
import { useDemo } from '../../demo/demoMode'

// Explains why governance data is not shown instead of showing an empty page.
function AccessGate({ error, onSignIn }) {
  const { demo, enterDemo } = useDemo()
  if (!error) return null
  const tryDemo = !demo && <Button variant="secondary" onClick={enterDemo}><FlaskConical size={15} /> Explore the demo with sample data</Button>
  if (error.kind === 'signin') {
    return <div className="panel access-gate"><Lock size={22} /><strong>Sign in to view governance data</strong><p>Findings about this deployment's AWS account are private. They are shown to operator accounts only.</p><div className="demo-notice-actions"><Button variant="primary" onClick={onSignIn}>Sign in</Button>{tryDemo}</div></div>
  }
  if (error.kind === 'forbidden') {
    return <div className="panel access-gate"><ShieldAlert size={22} /><strong>Operator access required</strong><p>Your account is signed in but is not listed as an operator for this deployment. An administrator can add your email to CLOUDOPS_OPERATOR_EMAILS.</p>{tryDemo}</div>
  }
  return <div className="panel"><EmptyState error title="Unable to load data" description={error.message} /></div>
}

export default AccessGate
