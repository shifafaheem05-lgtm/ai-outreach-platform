import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCheck, Download, Loader2, MailCheck, Plus, Upload } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import LeadTable, { Filters, Pager, companyCol, contactCol, emailCol, regionCol, TierPill } from '../components/LeadTable'

const TEMPLATE =
  'company,website,industry,location,company_size,contact_name,contact_title,email\n' +
  'Example Agency,example-agency.com,Marketing Agency,"Austin, TX",11-50,Jane Doe,Founder,jane@example-agency.com\n'

const EMPTY = { company_name: '', website: '', industry: '', location: '', company_size: '', contact_name: '', contact_title: '', email: '' }

function downloadTemplate() {
  const url = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: 'leads-template.csv' })
  a.click()
  URL.revokeObjectURL(url)
}

export default function LeadDiscovery() {
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const [q, setQ] = useState('')
  const [emailStatus, setEmailStatus] = useState('')
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [notice, setNotice] = useState(null) // { type: 'ok' | 'error', text }

  const params = { q, email_status: emailStatus, page, page_size: 15 }
  const leads = useQuery({ queryKey: ['leads', params], queryFn: async () => (await api.get('/leads', { params })).data, placeholderData: (p) => p })
  const caps = useQuery({ queryKey: ['lead-caps'], queryFn: async () => (await api.get('/leads/capabilities')).data })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['leads'] })
    qc.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const ok = (text) => setNotice({ type: 'ok', text })
  const fail = (e) => setNotice({ type: 'error', text: errorMessage(e) })

  const upload = useMutation({
    mutationFn: async (file) => {
      const fd = new FormData()
      fd.append('file', file)
      return (await api.post('/leads/import-csv', fd)).data
    },
    onSuccess: (r) => {
      ok(`Imported ${r.created} new, skipped ${r.duplicates} duplicate${r.duplicates === 1 ? '' : 's'}${r.skipped ? `, ${r.skipped} unusable row(s)` : ''}.`)
      refresh()
    },
    onError: fail,
  })
  const verify = useMutation({
    mutationFn: async () => (await api.post('/leads/verify', {})).data,
    onSuccess: (r) => {
      ok(r.checked ? `Checked ${r.checked}: ${r.valid} valid, ${r.risky} risky, ${r.invalid} invalid, ${r.unverified} could not be checked.` : 'No unverified emails left.')
      refresh()
    },
    onError: fail,
  })
  const dedupe = useMutation({
    mutationFn: async () => (await api.post('/leads/dedupe')).data,
    onSuccess: (r) => {
      ok(`Removed ${r.removed} duplicate${r.removed === 1 ? '' : 's'}${r.kept_because_of_history ? ` (${r.kept_because_of_history} kept: they have outreach history)` : ''}.`)
      refresh()
    },
    onError: fail,
  })
  const create = useMutation({
    mutationFn: async () => (await api.post('/leads', form)).data,
    onSuccess: () => {
      ok('Lead added.')
      setForm(EMPTY)
      setShowForm(false)
      refresh()
    },
    onError: fail,
  })

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const data = leads.data
  const columns = [
    companyCol,
    contactCol,
    emailCol,
    regionCol,
    { key: 'tier', label: 'Tier', render: (l) => <TierPill tier={l.tier} /> },
    { key: 'source', label: 'Source', className: 'text-xs capitalize text-slate-500' },
  ]

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <h2 className="font-semibold text-slate-900 dark:text-white">Add leads</h2>
          <p className="mt-1 text-sm text-slate-500">
            Import a CSV (company, website, email, title&hellip; any column order) or add one by hand. Duplicates are skipped automatically by email or website.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files[0] && upload.mutate(e.target.files[0])} />
            <button className="btn-primary" disabled={upload.isPending} onClick={() => { fileRef.current.value = ''; fileRef.current.click() }}>
              {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Import CSV
            </button>
            <button className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-white/10 dark:text-slate-200 dark:hover:bg-white/5" onClick={() => setShowForm(!showForm)}>
              <Plus className="mr-1 inline h-4 w-4" /> Add manually
            </button>
            <button className="rounded-xl px-3 py-2.5 text-sm font-medium text-brand-700 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-900/20" onClick={downloadTemplate}>
              <Download className="mr-1 inline h-4 w-4" /> CSV template
            </button>
          </div>
          {showForm && (
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
              <div className="sm:col-span-2">
                <label className="label" htmlFor="f-company">Company *</label>
                <input id="f-company" className="input" value={form.company_name} onChange={set('company_name')} required />
              </div>
              {[['website', 'Website'], ['email', 'Email'], ['contact_name', 'Contact name'], ['contact_title', 'Title'], ['industry', 'Industry'], ['location', 'Location'], ['company_size', 'Size (e.g. 11-50)']].map(([k, label]) => (
                <div key={k}>
                  <label className="label" htmlFor={`f-${k}`}>{label}</label>
                  <input id={`f-${k}`} className="input" value={form[k]} onChange={set(k)} />
                </div>
              ))}
              <div className="sm:col-span-2">
                <button className="btn-primary" disabled={create.isPending}>
                  {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save lead
                </button>
              </div>
            </form>
          )}
        </div>

        <div className="card">
          <h2 className="font-semibold text-slate-900 dark:text-white">Clean up</h2>
          <div className="mt-3 space-y-2">
            <button className="btn-primary w-full" disabled={verify.isPending} onClick={() => verify.mutate()}>
              {verify.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <MailCheck className="h-4 w-4" />} Verify emails
            </button>
            <button className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-white/10 dark:text-slate-200 dark:hover:bg-white/5" disabled={dedupe.isPending} onClick={() => dedupe.mutate()}>
              <CheckCheck className="mr-1 inline h-4 w-4" /> Remove duplicates
            </button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">
            {caps.data?.email_verification.note} Verification is free (DNS lookup), up to 200 emails per click.
          </p>
        </div>
      </div>

      {notice && (
        <div role="status" className={`rounded-xl px-4 py-3 text-sm ${notice.type === 'ok' ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300'}`}>
          {notice.text}
        </div>
      )}

      <div className="card">
        <Filters
          q={q}
          setQ={(v) => { setQ(v); setPage(1) }}
          extra={
            <select className="input w-auto" value={emailStatus} onChange={(e) => { setEmailStatus(e.target.value); setPage(1) }} aria-label="Filter by email status">
              <option value="">All emails</option>
              {['valid', 'risky', 'invalid', 'unverified'].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          }
        />
        <div className="mt-4">
          {leads.isLoading ? (
            <div className="py-10 text-center text-sm text-slate-500">Loading&hellip;</div>
          ) : (
            <LeadTable leads={data?.items ?? []} columns={columns} empty="No leads match. Import a CSV or add one above." />
          )}
        </div>
        {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} setPage={setPage} />}
      </div>
    </div>
  )
}
