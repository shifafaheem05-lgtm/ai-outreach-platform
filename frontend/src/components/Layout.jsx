import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { LogOut, Menu, Moon, Sparkles, Sun, X } from 'lucide-react'
import { NAV } from '../navigation'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'

function SidebarContent({ onNavigate }) {
  return (
    <div className="flex h-full flex-col bg-ink-950 text-slate-300">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-lg shadow-brand-900/40">
          <Sparkles className="h-5 w-5 text-white" />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold text-white">AI Outreach Pro</div>
          <div className="text-[11px] text-slate-500">B2B outreach automation</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            onClick={onNavigate}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                isActive
                  ? 'bg-brand-600/20 text-white ring-1 ring-brand-500/30'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`
            }
          >
            <Icon className="h-[18px] w-[18px] shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export default function Layout() {
  const [open, setOpen] = useState(false)
  const [dark, setDark] = useState(document.documentElement.classList.contains('dark'))
  const { user, logout } = useAuth()
  const [demoBanner, setDemoBanner] = useState(null)  // null | 'demo' | 'static'
  useEffect(() => {
    api.get('/auth/config').then((r) => setDemoBanner(r.data.static_preview ? 'static' : r.data.demo_mode ? 'demo' : null)).catch(() => {})
  }, [])
  const location = useLocation()
  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)))

  const toggleTheme = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem('aop_theme', next ? 'dark' : 'light')
    setDark(next)
  }

  return (
    <div className="min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 shadow-2xl">
            <SidebarContent onNavigate={() => setOpen(false)} />
          </div>
          <button
            aria-label="Close menu"
            onClick={() => setOpen(false)}
            className="absolute right-4 top-4 rounded-lg bg-white/10 p-2 text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      )}

      <div className="lg:pl-64">
        {demoBanner && (
          <div className="bg-brand-600 px-4 py-1.5 text-center text-xs font-medium text-white">
            {demoBanner === 'static'
              ? 'Interactive preview with sample data. Actions that change data are switched off here; the full app runs from the GitHub repo.'
              : 'Public demo: sample data, sending real email is disabled.'}
          </div>
        )}
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200/70 bg-white/80 px-4 py-3 backdrop-blur dark:border-white/5 dark:bg-ink-950/80 sm:px-8">
          <button
            aria-label="Open menu"
            onClick={() => setOpen(true)}
            className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-white/5 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <h1 className="text-lg font-semibold text-slate-900 dark:text-white">{current?.label ?? 'AI Outreach Pro'}</h1>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={toggleTheme}
              aria-label="Toggle dark mode"
              className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/5"
            >
              {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <div className="hidden text-right leading-tight sm:block">
              <div className="text-sm font-medium text-slate-900 dark:text-white">{user?.name}</div>
              <div className="text-xs capitalize text-slate-500">{user?.role}</div>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-700 dark:bg-brand-900/50 dark:text-brand-200">
              {user?.name?.[0]?.toUpperCase()}
            </div>
            <button
              onClick={logout}
              aria-label="Sign out"
              className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-white/5"
            >
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>
        <main className="px-4 py-6 sm:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
