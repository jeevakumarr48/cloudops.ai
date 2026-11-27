import { useState } from 'react'
import { LogIn, X } from 'lucide-react'
import Button from './ui/Button'
import { describeError } from '../services/api'

function AuthDialog({ onClose, onLogin, onRegister }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await onLogin(email, password)
      else await onRegister(email, password, displayName)
      onClose()
    } catch (err) {
      const described = describeError(err)
      setError(described.kind === 'signin' ? 'Email or password is incorrect.' : described.message)
    } finally {
      setBusy(false)
    }
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
    <form className="modal auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title" onSubmit={submit}>
      <div className="modal-head">
        <h2 id="auth-title">{mode === 'login' ? 'Sign in' : 'Create account'}</h2>
        <button type="button" className="plain-icon-button" onClick={onClose} aria-label="Close"><X size={17} /></button>
      </div>
      <label className="field"><span>Email</span><input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      {mode === 'register' && <label className="field"><span>Display name (optional)</span><input maxLength={80} value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label>}
      <label className="field"><span>Password{mode === 'register' ? ' (at least 12 characters)' : ''}</span><input type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={mode === 'register' ? 12 : 1} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <p className="form-error" role="alert">{error}</p>}
      <Button type="submit" variant="primary" disabled={busy}><LogIn size={15} /> {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</Button>
      <p className="modal-foot">{mode === 'login' ? 'No account yet?' : 'Already have an account?'} <button type="button" className="text-button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}>{mode === 'login' ? 'Create one' : 'Sign in'}</button></p>
      <p className="modal-note">Governance data for this deployment's AWS account is visible only to operator accounts.</p>
    </form>
  </div>
}

export default AuthDialog
