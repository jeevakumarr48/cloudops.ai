import './ui.css'

function Card({ as: Tag = 'section', className = '', children, ...rest }) {
  const classes = ['ui-card', className].filter(Boolean).join(' ')
  return <Tag className={classes} {...rest}>{children}</Tag>
}

export default Card
