import './ui.css'

function StatusPill({ tone = 'neutral', className = '', children, ...rest }) {
  const classes = ['ui-status', `ui-status--${tone}`, className].filter(Boolean).join(' ')
  return (
    <span className={classes} {...rest}>
      <i className="ui-status__dot" aria-hidden="true" />
      {children}
    </span>
  )
}

export default StatusPill
