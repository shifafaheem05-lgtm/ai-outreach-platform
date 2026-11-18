import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import api, { tokenStore } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokenStore.access))

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    if (!tokenStore.access) return
    api
      .get('/auth/me')
      .then((r) => setUser(r.data))
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    window.addEventListener('aop:logout', logout)
    return () => window.removeEventListener('aop:logout', logout)
  }, [logout])

  const login = async (email, password) => {
    const { data } = await api.post('/auth/login', { email, password })
    tokenStore.set(data)
    setUser((await api.get('/auth/me')).data)
  }

  const register = async (payload) => {
    const { data } = await api.post('/auth/register', payload)
    tokenStore.set(data)
    setUser((await api.get('/auth/me')).data)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
