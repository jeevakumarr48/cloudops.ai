import './ui.css'

function Badge({ tone = 'neutral', className = '', children }) {
  const classes = ['ui-badge', `ui-badge--${tone}`, className].filter(Boolean).join(' ')
  return <span className={classes}>{children}</span>
}

export default Badge
