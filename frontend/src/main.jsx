import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, HashRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { AuthProvider } from './context/AuthContext'
import './index.css'

// GitHub Pages serves from a sub-path and cannot rewrite URLs, so the static preview uses hash routing.
const Router = import.meta.env.VITE_STATIC_DEMO === 'true' ? HashRouter : BrowserRouter

if (localStorage.getItem('aop_theme') === 'dark') document.documentElement.classList.add('dark')

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <Router>
        <AuthProvider>
          <App />
        </AuthProvider>
      </Router>
    </QueryClientProvider>
  </React.StrictMode>,
)
