export const SEVERITIES = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
export const CATEGORIES = ['SECURITY', 'COST', 'UTILIZATION', 'STORAGE', 'AVAILABILITY', 'CONFIGURATION', 'GOVERNANCE', 'INFRASTRUCTURE']
export const EVIDENCE_STATES = ['CONFIRMED', 'POTENTIAL', 'INSUFFICIENT_EVIDENCE']
export const FINDING_STATUSES = ['open', 'acknowledged', 'accepted_risk', 'false_positive', 'resolved']
export const SETTABLE_STATUSES = ['open', 'acknowledged', 'accepted_risk', 'false_positive']
export const DECISIONS = [
  ['accepted', 'Accept'],
  ['rejected', 'Reject'],
  ['remediation_in_progress', 'In progress'],
  ['remediated_pending_verification', 'Remediated, verify'],
]

export const severityTone = (s) => ({ CRITICAL: 'danger', HIGH: 'danger', MEDIUM: 'warn', LOW: 'info', INFO: 'neutral' }[s] || 'neutral')
export const stateTone = (s) => ({ CONFIRMED: 'danger', POTENTIAL: 'warn', INSUFFICIENT_EVIDENCE: 'neutral' }[s] || 'neutral')
export const sourceTone = (s) => (s === 'ok' ? 'ok' : 'warn')

const pretty = { INSUFFICIENT_EVIDENCE: 'Insufficient evidence', accepted_risk: 'Accepted risk', false_positive: 'False positive',
  remediation_in_progress: 'Remediation in progress', remediated_pending_verification: 'Remediated, pending verification' }
export const label = (value) => pretty[value] || (value ? value.charAt(0) + value.slice(1).toLowerCase().replaceAll('_', ' ') : '')

export const formatDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}
