import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Info, Loader2 } from 'lucide-react'
import api, { errorMessage } from '../api/client'

export const Spinner = ({ className = 'h-4 w-4' }) => <Loader2 className={`${className} animate-spin`} />

const KIND = {
  ok: ['bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300', CheckCircle2],
  error: ['bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300', AlertCircle],
  info: ['bg-brand-50 text-brand-900 dark:bg-brand-900/20 dark:text-brand-100', Info],
}

export function Notice({ kind = 'info', children }) {
  if (!children) return null
  const [cls, Icon] = KIND[kind]
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex gap-2.5 rounded-xl px-4 py-3 text-sm ${cls}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export const ErrorNotice = ({ error }) => (error ? <Notice kind="error">{errorMessage(error)}</Notice> : null)

const STATUS = {
  running: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  completed: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
  approved: 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300',
  pending_approval: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  paused: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  draft: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
}
export const StatusPill = ({ status }) => (
  <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${STATUS[status] ?? STATUS.draft}`}>{String(status).replace(/_/g, ' ')}</span>
)

export const Card = ({ title, action, children, className = '' }) => (
  <div className={`card ${className}`}>
    {(title || action) && (
      <div className="mb-3 flex items-center justify-between gap-3">
        {title && <h2 className="font-semibold text-slate-900 dark:text-white">{title}</h2>}
        {action}
      </div>
    )}
    {children}
  </div>
)

export const Empty = ({ children }) => <p className="py-8 text-center text-sm text-slate-500">{children}</p>

export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—')

/** Searchable lead dropdown. Calls onChange(lead). */
export function LeadPicker({ value, onChange, label = 'Lead' }) {
  const [q, setQ] = useState('')
  const { data } = useQuery({
    queryKey: ['lead-picker', q],
    queryFn: async () => (await api.get('/leads', { params: { q, page_size: 30, sort: 'score' } })).data,
    placeholderData: (p) => p,
  })
  const items = data?.items ?? []
  return (
    <div>
      <label className="label" htmlFor="lead-q">{label}</label>
      <input id="lead-q" className="input" placeholder="Search leads…" value={q} onChange={(e) => setQ(e.target.value)} />
      <select className="input mt-2" size={5} value={value?.id ?? ''} onChange={(e) => onChange(items.find((l) => String(l.id) === e.target.value) ?? null)} aria-label="Choose a lead">
        {items.map((l) => (
          <option key={l.id} value={l.id}>
            {l.company_name}{l.contact_name ? ` · ${l.contact_name}` : ''} ({l.score})
          </option>
        ))}
      </select>
    </div>
  )
}

/** Authenticated file download (CSV / XLSX). */
export async function downloadFile(path, filename) {
  const res = await api.get(path, { responseType: 'blob' })
  const url = URL.createObjectURL(res.data)
  Object.assign(document.createElement('a'), { href: url, download: filename }).click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const copyText = (text) => navigator.clipboard?.writeText(text)
