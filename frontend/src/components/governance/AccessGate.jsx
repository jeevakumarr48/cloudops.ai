import { Lock, ShieldAlert } from 'lucide-react'
import Button from '../ui/Button'
import EmptyState from '../EmptyState'

// Explains why governance data is not shown instead of showing an empty page.
function AccessGate({ error, onSignIn }) {
  if (!error) return null
  if (error.kind === 'signin') {
    return <div className="panel access-gate"><Lock size={22} /><strong>Sign in to view governance data</strong><p>Findings about this deployment's AWS account are private. They are shown to operator accounts only.</p><Button variant="primary" onClick={onSignIn}>Sign in</Button></div>
  }
  if (error.kind === 'forbidden') {
    return <div className="panel access-gate"><ShieldAlert size={22} /><strong>Operator access required</strong><p>Your account is signed in but is not listed as an operator for this deployment. An administrator can add your email to CLOUDOPS_OPERATOR_EMAILS.</p></div>
  }
  return <div className="panel"><EmptyState error title="Unable to load data" description={error.message} /></div>
}

export default AccessGate
