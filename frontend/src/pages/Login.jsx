import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Loader2, Sparkles } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api, { errorMessage } from '../api/client'

export default function Login() {
  const { user, login, register } = useAuth()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ email: '', password: '', name: '', organization_name: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [canRegister, setCanRegister] = useState(true)
  const [demo, setDemo] = useState(null)  // { email, password, preview } when the server runs in public-demo mode

  useEffect(() => {
    api.get('/auth/config').then((r) => {
      setCanRegister(r.data.allow_registration !== false)
      if (r.data.demo_mode) setDemo({ email: r.data.demo_email, password: r.data.demo_password, preview: !!r.data.static_preview })
    }).catch(() => {})
  }, [])

  const tryDemo = async () => {
    setError('')
    setBusy(true)
    try {
      await login(demo.email, demo.password)
    } catch (err) {
      setError(errorMessage(err, 'Could not open the demo'))
    } finally {
      setBusy(false)
    }
  }

  if (user) return <Navigate to="/" replace />

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      if (mode === 'login') await login(form.email, form.password)
      else await register(form)
    } catch (err) {
      setError(errorMessage(err, 'Could not sign in'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-ink-950 p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -left-24 top-1/3 h-96 w-96 rounded-full bg-brand-600/30 blur-3xl" />
        <div className="absolute -right-16 bottom-0 h-72 w-72 rounded-full bg-brand-400/20 blur-3xl" />
        <div className="relative flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <span className="text-lg font-semibold text-white">AI Outreach Pro</span>
        </div>
        <div className="relative max-w-md">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight text-white">
            From first research to booked meeting, in one workspace.
          </h2>
          <p className="mt-4 text-slate-400">
            Discover prospects, research their business, write personalized emails and video scripts, and follow up
            with your approval at every step.
          </p>
        </div>
        <p className="relative text-xs text-slate-500">Compliance-first: suppression lists, unsubscribe links, human approval.</p>
      </div>

      <div className="flex items-center justify-center bg-white p-6 dark:bg-ink-950">
        <form onSubmit={submit} className="w-full max-w-sm space-y-5">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">
              {mode === 'login' ? 'Welcome back' : 'Create your workspace'}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {mode === 'login' ? 'Sign in to continue.' : 'You will be the admin of your new organization.'}
            </p>
          </div>

          {mode === 'register' && (
            <>
              <div>
                <label className="label" htmlFor="name">Your name</label>
                <input id="name" className="input" value={form.name} onChange={set('name')} required />
              </div>
              <div>
                <label className="label" htmlFor="org">Organization</label>
                <input id="org" className="input" value={form.organization_name} onChange={set('organization_name')} required />
              </div>
            </>
          )}
          <div>
            <label className="label" htmlFor="email">Email</label>
            <input id="email" type="email" className="input" value={form.email} onChange={set('email')} required autoComplete="email" />
          </div>
          <div>
            <label className="label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              value={form.password}
              onChange={set('password')}
              required
              minLength={mode === 'register' ? 8 : undefined}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
            {mode === 'register' && <p className="mt-1 text-xs text-slate-500">At least 8 characters.</p>}
          </div>

          {error && (
            <div role="alert" className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
          )}

          <button className="btn-primary w-full" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </button>

          {demo && mode === 'login' && (
            <div className="rounded-xl border border-brand-200 bg-brand-50 p-3.5 text-sm dark:border-brand-700/40 dark:bg-brand-900/20">
              <p className="font-medium text-brand-800 dark:text-brand-200">Public demo with sample data</p>
              <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400">
                {demo.preview
                  ? 'Interactive preview with sample data. Browse every page; actions that change data are switched off. The full app runs from the GitHub repo.'
                  : 'Look around with the shared demo account, or create your own workspace and try it with your own leads. Sending real email is turned off here.'}
              </p>
              <button type="button" className="btn-secondary mt-2.5 w-full" disabled={busy} onClick={tryDemo}>
                Try the demo (no sign-up)
              </button>
            </div>
          )}

          {(canRegister || mode === 'register') && <p className="text-center text-sm text-slate-500">
            {mode === 'login' ? 'New here?' : 'Already have an account?'}{' '}
            <button
              type="button"
              className="font-medium text-brand-600 hover:text-brand-700 dark:text-brand-300"
              onClick={() => {
                setMode(mode === 'login' ? 'register' : 'login')
                setError('')
              }}
            >
              {mode === 'login' ? 'Create a workspace' : 'Sign in'}
            </button>
          </p>}

          {import.meta.env.DEV && mode === 'login' && (
            <button
              type="button"
              className="w-full rounded-xl border border-dashed border-brand-300 px-3 py-2 text-xs text-brand-700 hover:bg-brand-50 dark:border-brand-700 dark:text-brand-300 dark:hover:bg-brand-900/20"
              onClick={() => setForm({ ...form, email: 'demo@aioutreach.pro', password: 'Demo1234!' })}
            >
              Fill demo credentials (dev only)
            </button>
          )}
        </form>
      </div>
    </div>
  )
}
