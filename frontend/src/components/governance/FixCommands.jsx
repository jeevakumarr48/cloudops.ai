import { useState } from 'react'
import { Check, ChevronDown, Copy, Terminal, TriangleAlert } from 'lucide-react'
import Badge from '../ui/Badge'
import { IMPACT, copyText, fixScript } from './fixHelpers'

function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false)
  const copy = async () => {
    if (await copyText(text)) { setDone(true); window.setTimeout(() => setDone(false), 1500) }
  }
  return <button type="button" className="plain-icon-button fix-copy" onClick={copy} aria-label={`${label} command`}>
    {done ? <Check size={14} /> : <Copy size={14} />}<span>{done ? 'Copied' : label}</span>
  </button>
}

function Command({ step }) {
  const [tone, text] = IMPACT[step.impact] || IMPACT.safe
  return <li className={`fix-step fix-step--${step.impact}`}>
    <div className="fix-step-head"><span>{step.label}</span><span className="fix-step-tools"><Badge tone={tone}>{text}</Badge><CopyButton text={step.command} /></span></div>
    <pre className="fix-code"><code>{step.command}</code></pre>
  </li>
}

function FixCommands({ fix }) {
  const [open, setOpen] = useState(false)
  if (!fix) return null
  const [tone, text] = IMPACT[fix.impact] || IMPACT.safe
  return <section className={`fix-panel${open ? ' is-open' : ''}`}>
    <button type="button" className="fix-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
      <Terminal size={15} /><strong>How to fix it</strong><span className="muted">AWS CLI commands you run yourself</span>
      <Badge tone={tone}>{text}</Badge><ChevronDown size={15} className="fix-chevron" />
    </button>
    {open && <div className="fix-body">
      <p className="fix-notice"><TriangleAlert size={14} /> {fix.notice}</p>
      <p>{fix.summary}</p>
      {fix.placeholders.length > 0 && <p className="fix-placeholders">Fill in before running: {fix.placeholders.map((p) => <code key={p}>{p}</code>)}</p>}
      {fix.before.length > 0 && <><h4>1. Record the current state</h4><ol className="fix-steps">{fix.before.map((s) => <Command key={s.command} step={s} />)}</ol></>}
      <h4>{fix.before.length ? '2.' : '1.'} Make the change</h4>
      <ol className="fix-steps">{fix.steps.map((s) => <Command key={s.command} step={s} />)}</ol>
      {fix.verify && <><h4>Check it worked</h4><ol className="fix-steps"><Command step={{ label: 'Verify', command: fix.verify, impact: 'read_only' }} /></ol></>}
      <h4>Undo</h4>
      {fix.undo ? (fix.undo.startsWith('aws ') ? <ol className="fix-steps"><Command step={{ label: 'Reverse the change', command: fix.undo, impact: 'safe' }} /></ol> : <p>{fix.undo}</p>)
        : <p className="fix-no-undo">This cannot be undone. Keep the backup from the first step.</p>}
      {fix.notes.length > 0 && <ul className="fix-notes">{fix.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <div className="fix-actions"><CopyButton text={fixScript(fix)} label="Copy all as a script" /></div>
    </div>}
  </section>
}

export default FixCommands
