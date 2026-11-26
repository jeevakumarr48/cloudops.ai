// Shared helpers for the fix commands and the fix-first plan.

export const IMPACT = {
  read_only: ['ok', 'Read only'],
  safe: ['ok', 'Low risk'],
  disruptive: ['warn', 'Can disrupt clients'],
  destructive: ['danger', 'Permanent'],
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Clipboard API is unavailable on insecure origins; fall back to a hidden textarea.
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    area.remove()
    return ok
  }
}

export function fixScript(fix) {
  const lines = ['# ' + fix.notice, '# ' + fix.summary]
  const add = (title, steps) => {
    if (!steps.length) return
    lines.push('', '# --- ' + title)
    steps.forEach((s) => lines.push('# ' + s.label + (s.impact === 'destructive' ? ' (PERMANENT)' : ''), s.command))
  }
  add('Record the current state first', fix.before)
  add('Make the change', fix.steps)
  if (fix.verify) lines.push('', '# --- Check it worked', fix.verify)
  return lines.join('\n') + '\n'
}

export function jumpToRecommendation(recommendationId) {
  const card = document.getElementById(`rec-${recommendationId}`)
  if (!card) return
  card.scrollIntoView({ behavior: 'smooth', block: 'start' })
  card.classList.add('is-highlighted')
  window.setTimeout(() => card.classList.remove('is-highlighted'), 1600)
}
