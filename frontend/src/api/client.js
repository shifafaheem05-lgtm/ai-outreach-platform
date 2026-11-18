import axios from 'axios'

const ACCESS = 'aop_access'
const REFRESH = 'aop_refresh'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS)
  },
  get refresh() {
    return localStorage.getItem(REFRESH)
  },
  set({ access_token, refresh_token }) {
    localStorage.setItem(ACCESS, access_token)
    localStorage.setItem(REFRESH, refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
  },
}

const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use((config) => {
  if (tokenStore.access) config.headers.Authorization = `Bearer ${tokenStore.access}`
  return config
})

let refreshing = null

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    const isAuthCall = original?.url?.startsWith('/auth/')
    if (error.response?.status === 401 && !original._retry && !isAuthCall && tokenStore.refresh) {
      original._retry = true
      try {
        refreshing =
          refreshing ||
          axios.post('/api/v1/auth/refresh', { refresh_token: tokenStore.refresh }).finally(() => {
            refreshing = null
          })
        const { data } = await refreshing
        tokenStore.set(data)
        original.headers.Authorization = `Bearer ${data.access_token}`
        return api(original)
      } catch {
        tokenStore.clear()
        window.dispatchEvent(new Event('aop:logout'))
      }
    }
    return Promise.reject(error)
  },
)

export const errorMessage = (err, fallback = 'Something went wrong') => {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return fallback
}

export default api
