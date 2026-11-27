import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FixFirstPlan from './FixFirstPlan'

const group = (id, steps) => ({
  resource: { type: 'S3', id, region: 'us-east-1' }, top_severity: 'CRITICAL', top_priority_score: 70,
  finding_count: steps.length, start_with: steps[0], why_first: null, steps,
})
const step = (n, extra = {}) => ({ recommendation_id: `r${n}`, finding_id: `f${n}`, title: `Finding ${n}`, severity: 'HIGH',
  category: 'SECURITY', priority_score: 50, fix_impact: 'safe', quick_win: false, ...extra })

describe('FixFirstPlan', () => {
  it('lists resources in order with quick wins and permanent steps marked', () => {
    const plan = { summary: 'Start with S3 a.', total_groups: 1, quick_wins: 1,
      groups: [group('bucket-a', [step(1, { quick_win: true }), step(2, { fix_impact: 'destructive' })])] }
    render(<FixFirstPlan plan={plan} />)
    expect(screen.getByText('Start with S3 a.')).toBeInTheDocument()
    expect(screen.getByText('bucket-a')).toBeInTheDocument()
    expect(screen.getByText(/Quick win/)).toBeInTheDocument()
    expect(screen.getByText('Permanent')).toBeInTheDocument()
  })

  it('shows at most five resources and says how many more there are', () => {
    const groups = Array.from({ length: 7 }, (_, i) => group(`bucket-${i}`, [step(i)]))
    render(<FixFirstPlan plan={{ summary: 's', total_groups: 7, quick_wins: 0, groups }} />)
    expect(screen.getAllByRole('listitem').filter((li) => li.classList.contains('plan-group'))).toHaveLength(5)
    expect(screen.getByText(/2 more resource\(s\)/)).toBeInTheDocument()
  })

  it('jumps to the recommendation when a finding is clicked', async () => {
    const onJump = vi.fn()
    const plan = { summary: 's', total_groups: 1, quick_wins: 0, groups: [group('b', [step(9)])] }
    render(<FixFirstPlan plan={plan} onJump={onJump} />)
    await userEvent.click(screen.getByRole('button', { name: /Finding 9/ }))
    expect(onJump).toHaveBeenCalledWith('r9')
  })
})
