import { ListOrdered, Zap } from 'lucide-react'
import Badge from '../ui/Badge'
import { label, severityTone } from './labels'
import { IMPACT, jumpToRecommendation } from './fixHelpers'

const SHOWN = 5

function FixFirstPlan({ plan, onJump = jumpToRecommendation }) {
  if (!plan) return null
  const groups = plan.groups.slice(0, SHOWN)
  return <section className="panel fix-plan">
    <div className="panel-heading"><div><span className="eyebrow">Fix first</span><h2>Where to start</h2><p>Findings grouped by resource, most urgent first. One visit to a resource can clear several.</p></div><ListOrdered className="panel-heading-icon" size={20} /></div>
    <p className="posture-text">{plan.summary}</p>
    {groups.length > 0 && <ol className="plan-groups">
      {groups.map((g, i) => <li key={`${g.resource.type}:${g.resource.id}`} className="plan-group">
        <span className="plan-rank" aria-hidden="true">{i + 1}</span>
        <div className="plan-main">
          <div className="plan-title"><Badge tone={severityTone(g.top_severity)}>{g.top_severity}</Badge><span className="sub">{g.resource.type}</span><strong className="resource-id">{g.resource.id}</strong><span className="muted">{g.finding_count} finding(s)</span></div>
          {g.why_first && <p className="plan-why">{g.why_first}</p>}
          <ul className="plan-steps">{g.steps.map((s) => <li key={s.recommendation_id}>
            <button type="button" className="plan-step" onClick={() => onJump(s.recommendation_id)}>
              <span>{s.title}</span>
              <span className="plan-step-tags">
                <span className="muted">{label(s.severity)}</span>
                {s.quick_win && <Badge tone="ok"><Zap size={11} /> Quick win</Badge>}
                {s.fix_impact === 'destructive' && <Badge tone={IMPACT.destructive[0]}>{IMPACT.destructive[1]}</Badge>}
              </span>
            </button>
          </li>)}</ul>
        </div>
      </li>)}
    </ol>}
    {plan.total_groups > SHOWN && <p className="muted">{plan.total_groups - SHOWN} more resource(s) are listed below in priority order.</p>}
  </section>
}

export default FixFirstPlan
