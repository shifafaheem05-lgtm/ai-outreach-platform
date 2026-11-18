import { ChevronLeft, ChevronRight, Search } from 'lucide-react'

const TIER = {
  hot: 'bg-brand-600 text-white',
  warm: 'bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-200',
  cold: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
}
const EMAIL = {
  valid: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  risky: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  invalid: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300',
  unverified: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
}

export const Pill = ({ children, className = '' }) => (
  <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${className}`}>{children}</span>
)

export const TierPill = ({ tier }) => <Pill className={TIER[tier] ?? TIER.cold}>{tier}</Pill>

export function Filters({ q, setQ, extra }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-[200px] flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input className="input pl-9" placeholder="Search company, contact, email, industry" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {extra}
    </div>
  )
}

export function Pager({ page, pageSize, total, setPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center justify-between pt-3 text-xs text-slate-500">
      <span>{total} lead{total === 1 ? '' : 's'}</span>
      <div className="flex items-center gap-1">
        <button className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-white/5" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span>Page {page} of {pages}</span>
        <button className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-white/5" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

/** columns: [{ key, label, render?(lead), className? }] */
export default function LeadTable({ leads, columns, onRowClick, selectedId, empty = 'No leads yet.' }) {
  if (!leads.length) return <p className="py-10 text-center text-sm text-slate-500">{empty}</p>
  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200/70 text-xs uppercase tracking-wide text-slate-500 dark:border-white/5">
            {columns.map((c) => (
              <th key={c.key} className={`px-5 py-2.5 font-medium ${c.className ?? ''}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr
              key={l.id}
              onClick={onRowClick ? () => onRowClick(l) : undefined}
              className={`border-b border-slate-100 transition last:border-0 dark:border-white/5 ${onRowClick ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-white/5' : ''} ${selectedId === l.id ? 'bg-brand-50/70 dark:bg-brand-900/20' : ''}`}
            >
              {columns.map((c) => (
                <td key={c.key} className={`px-5 py-3 ${c.className ?? ''}`}>{c.render ? c.render(l) : l[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const companyCol = {
  key: 'company_name',
  label: 'Company',
  render: (l) => (
    <div>
      <div className="font-medium text-slate-900 dark:text-white">{l.company_name}</div>
      <div className="text-xs text-slate-500">{[l.industry, l.location].filter(Boolean).join(' · ') || '—'}</div>
    </div>
  ),
}
export const contactCol = {
  key: 'contact',
  label: 'Contact',
  render: (l) => (
    <div>
      <div className="text-slate-800 dark:text-slate-200">{l.contact_name || '—'}</div>
      <div className="text-xs text-slate-500">{l.contact_title}</div>
    </div>
  ),
}
export const emailCol = {
  key: 'email',
  label: 'Email',
  render: (l) =>
    l.email ? (
      <div className="flex flex-col items-start gap-1">
        <span className="text-xs">{l.email}</span>
        <Pill className={EMAIL[l.email_status] ?? EMAIL.unverified}>{l.email_status}</Pill>
      </div>
    ) : (
      <span className="text-slate-400">—</span>
    ),
}
export const regionCol = {
  key: 'region',
  label: '',
  render: (l) =>
    l.region_flag ? (
      <span title="EU/UK contact: you need a documented lawful basis before emailing" className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
        EU/UK
      </span>
    ) : null,
}
