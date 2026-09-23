import './ui.css'

function Button({ variant = 'secondary', size = 'md', className = '', type = 'button', children, ...rest }) {
  const classes = ['ui-btn', `ui-btn--${variant}`, size && `ui-btn--${size}`, className].filter(Boolean).join(' ')
  return <button type={type} className={classes} {...rest}>{children}</button>
}

export default Button
