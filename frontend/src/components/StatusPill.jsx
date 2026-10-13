import { Badge } from '@/components/ui/badge'

// Status pill on top of shadcn's Badge: hue + word + dot, never hue alone.
const TONES = {
  ok: 'bg-success-background text-success',
  connected: 'bg-success-background text-success',
  warn: 'bg-warning-background text-warning',
  amber: 'bg-warning-background text-warning',
  danger: 'bg-destructive/10 text-destructive',
  red: 'bg-destructive/10 text-destructive',
  info: 'bg-info-background text-info',
  blue: 'bg-info-background text-info',
  neutral: 'bg-muted text-muted-foreground',
}

function StatusPill({ tone = 'neutral', className = '', children, ...rest }) {
  return (
    <Badge
      variant="outline"
      className={`h-6 gap-1.5 rounded-full border-transparent px-2.5 text-xs font-medium ${TONES[tone] || TONES.neutral} ${className}`}
      {...rest}
    >
      <i className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {children}
    </Badge>
  )
}

export default StatusPill
