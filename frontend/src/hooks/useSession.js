import { useCallback, useEffect, useState } from 'react'
import { describeError, getMe, login as apiLogin, logout as apiLogout, register as apiRegister } from '../services/api'

// Session state from the HttpOnly cookie. The browser never sees the token;
// /api/auth/me tells us who is signed in.
export default function useSession() {
  const [state, setState] = useState({ status: 'loading', me: null, accountsAvailable: true })

  const refresh = useCallback(async () => {
    try {
      const { data } = await getMe()
      setState({ status: 'signed_in', me: data, accountsAvailable: true })
    } catch (error) {
      const { kind } = describeError(error)
      setState({ status: 'signed_out', me: null, accountsAvailable: kind !== 'unavailable' })
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(refresh, 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  const login = async (email, password) => {
    const { data } = await apiLogin(email, password)
    setState({ status: 'signed_in', me: data, accountsAvailable: true })
  }
  const register = async (email, password, displayName) => {
    const { data } = await apiRegister(email, password, displayName)
    setState({ status: 'signed_in', me: data, accountsAvailable: true })
  }
  const logout = async () => {
    try { await apiLogout() } finally { setState((s) => ({ ...s, status: 'signed_out', me: null })) }
  }

  return { ...state, isOperator: Boolean(state.me?.is_operator), refresh, login, register, logout }
}
