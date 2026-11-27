import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FixCommands from './FixCommands'

const fix = {
  notice: 'CloudOps never runs these commands.',
  summary: 'Keep a backup image, then terminate the instance.',
  impact: 'destructive',
  placeholders: ['<OWNER>'],
  before: [],
  steps: [
    { label: 'Create a backup image', command: 'aws ec2 create-image --instance-id i-1', impact: 'safe' },
    { label: 'Terminate the instance', command: 'aws ec2 terminate-instances --instance-ids i-1', impact: 'destructive' },
  ],
  verify: 'aws ec2 describe-instances --instance-ids i-1',
  undo: null,
  notes: ['Termination cannot be undone.'],
}

describe('FixCommands', () => {
  it('renders nothing when there is no fix', () => {
    const { container } = render(<FixCommands fix={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('starts collapsed and shows the overall impact', () => {
    render(<FixCommands fix={fix} />)
    expect(screen.getByRole('button', { name: /How to fix it/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Permanent')).toBeInTheDocument()
    expect(screen.queryByText(fix.notice)).not.toBeInTheDocument()
  })

  it('shows the notice, placeholders, steps and the no-undo warning when opened', async () => {
    render(<FixCommands fix={fix} />)
    await userEvent.click(screen.getByRole('button', { name: /How to fix it/ }))
    expect(screen.getByText(fix.notice)).toBeInTheDocument()
    expect(screen.getByText('<OWNER>')).toBeInTheDocument()
    expect(screen.getByText(/terminate-instances/)).toBeInTheDocument()
    expect(screen.getByText(/cannot be undone. Keep the backup/)).toBeInTheDocument()
  })

  it('copies a single command to the clipboard', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    render(<FixCommands fix={fix} />)
    await user.click(screen.getByRole('button', { name: /How to fix it/ }))
    await user.click(screen.getAllByRole('button', { name: 'Copy command' })[0])
    expect(writeText).toHaveBeenCalledWith('aws ec2 create-image --instance-id i-1')
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })
})
