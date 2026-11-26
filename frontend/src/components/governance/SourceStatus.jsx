import StatusPill from '../ui/StatusPill'
import { sourceTone } from './labels'

const names = { ec2: 'EC2', s3: 'S3', rds: 'RDS', cost: 'Cost Explorer' }

// One pill per data source. An unavailable source is never shown as "no issues".
function SourceStatus({ sources }) {
  if (!sources) return null
  return <div className="source-status" aria-label="Data sources">
    {Object.entries(sources).map(([name, s]) => <StatusPill key={name} tone={sourceTone(s.status)} title={s.error || `${s.evaluated_rules} rule evaluations`}>
      {names[name] || name}: {s.status === 'ok' ? 'scanned' : 'unavailable'}
    </StatusPill>)}
  </div>
}

export default SourceStatus
