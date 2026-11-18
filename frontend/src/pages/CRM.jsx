import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileSpreadsheet, Trash2 } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import LeadTable, { Filters, Pager, Pill, TierPill, companyCol, contactCol, regionCol } from '../components/LeadTable'
import { useAuth } from '../context/AuthContext'
import { Card, Empty, ErrorNotice, Notice, Spinner, downloadFile, fmtDate } from '../components/ui'

const STATUSES = ['new', 'contacted', 'replied', 'meeting', 'won', 'lost', 'unsubscribed']

function Profile({ id, onDeleted }) {
  const qc = useQueryClient()
  const { user } = useAuth()
  const [note, setNote] = useState('')
  const [tags, setTags] = useState(null)
  const p = useQuery({ queryKey: ['crm', id], queryFn: async () => (await api.get(`/crm/leads/${id}`)).data })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['crm', id] }); qc.invalidateQueries({ queryKey: ['leads'] }) }
  const patch = useMutation({ mutationFn: async (b) => api.patch(`/leads/${id}`, b), onSuccess: refresh })
  const addNote = useMutation({ mutationFn: async () => api.post(`/crm/leads/${id}/notes`, { body: note }), onSuccess: () => { setNote(''); refresh() } })
  const delLead = useMutation({ mutationFn: async () => api.delete(`/leads/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['leads'] }); onDeleted() } })
  const delNote = useMutation({ mutationFn: async (nid) => api.delete(`/crm/leads/${id}/notes/${nid}`), onSuccess: refresh })
  if (p.isLoading) return <Card><Spinner /></Card>
  const { lead, conversation, research, videos, notes, score_breakdown: sb } = p.data
  const tagValue = tags ?? lead.tags.join(', ')
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-lg font-semibold">{lead.company_name}</h2><p className="text-xs text-slate-500">{[lead.industry, lead.location, lead.company_size].filter(Boolean).join(' · ')}</p>
            <p className="mt-1 text-sm">{lead.contact_name} {lead.contact_title && <span className="text-slate-500">({lead.contact_title})</span>}</p><p className="text-xs">{lead.email} <Pill className="bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300">{lead.email_status}</Pill></p>
            {lead.website && <a className="text-xs text-brand-600 hover:underline dark:text-brand-300" href={lead.website} target="_blank" rel="noreferrer noopener">{lead.website}</a>}</div>
          <div className="text-right"><TierPill tier={lead.tier} /><div className="mt-1 text-2xl font-semibold">{lead.score}</div>
            {['manager', 'admin'].includes(user.role) && <button className="mt-1 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-red-600" disabled={delLead.isPending} onClick={() => window.confirm(`Delete ${lead.company_name}? This cannot be undone.`) && delLead.mutate()}><Trash2 className="h-3.5 w-3.5" /> Delete lead</button>}</div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div><label className="label" htmlFor="st">Status</label><select id="st" className="input" value={lead.status} onChange={(e) => patch.mutate({ status: e.target.value })}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></div>
          <div><label className="label" htmlFor="tg">Tags (comma separated)</label><input id="tg" className="input" value={tagValue} onChange={(e) => setTags(e.target.value)} onBlur={() => tags !== null && patch.mutate({ tags: tags.split(',').map((t) => t.trim()).filter(Boolean) })} /></div>
        </div>
        <div className="mt-2"><ErrorNotice error={patch.error} /><ErrorNotice error={delLead.error} />{lead.region_flag && <p className="mt-2 text-xs text-amber-600">EU/UK contact: make sure you have a documented lawful basis before emailing.</p>}</div>
        {sb && <p className="mt-3 text-xs text-slate-500">Score breakdown ({sb.model}): {Object.entries(sb.features).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}</p>}
      </Card>

      <Card title="Conversation">
        {conversation.length === 0 ? <Empty>No emails yet.</Empty> : <ul className="space-y-3">{conversation.map((m) => (
          <li key={m.id} className={`rounded-xl p-3 text-sm ${m.direction === 'out' ? 'bg-brand-50/60 dark:bg-brand-900/10' : 'bg-slate-50 dark:bg-white/5'}`}>
            <div className="mb-1 flex justify-between text-xs text-slate-500"><span>{m.direction === 'out' ? 'Sent' : 'Received'} · {m.status}{m.label ? ` · ${m.label.replace(/_/g, ' ')}` : ''}</span><span>{fmtDate(m.at)}</span></div>
            <div className="font-medium">{m.subject}</div><p className="mt-1 whitespace-pre-wrap text-[13px]">{m.body}</p></li>))}</ul>}
      </Card>

      <Card title="Research">
        {research ? <div className="space-y-2 text-sm"><p>{research.summary}</p>{research.sources.length > 0 && <p className="text-xs text-slate-500">Sources: {research.sources.map((s) => s.url).join(', ')}</p>}</div> : <Empty>No research yet (see Lead Research).</Empty>}
      </Card>

      {videos.length > 0 && <Card title="Videos"><ul className="space-y-1 text-sm">{videos.map((v) => <li key={v.id}>{v.status.replace('_', ' ')}{v.loom_url && <> · <a className="text-brand-600 hover:underline dark:text-brand-300" href={v.loom_url} target="_blank" rel="noreferrer noopener">{v.loom_url}</a></>}</li>)}</ul></Card>}

      <Card title="Notes">
        <div className="flex gap-2"><input className="input" placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && note.trim() && addNote.mutate()} /><button className="btn-primary shrink-0" disabled={!note.trim() || addNote.isPending} onClick={() => addNote.mutate()}>Add</button></div>
        <ul className="mt-3 space-y-2">{notes.map((n) => <li key={n.id} className="flex items-start justify-between gap-3 rounded-xl bg-slate-50 p-3 text-sm dark:bg-white/5"><div><p className="whitespace-pre-wrap">{n.body}</p><p className="mt-1 text-[11px] text-slate-400">{fmtDate(n.at)}</p></div><button aria-label="Delete note" className="text-slate-400 hover:text-red-600" onClick={() => delNote.mutate(n.id)}><Trash2 className="h-4 w-4" /></button></li>)}</ul>
      </Card>
    </div>
  )
}

export default function CRM() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [sel, setSel] = useState(null)
  const [dlError, setDlError] = useState('')
  const download = async (path, name) => {
    setDlError('')
    try { await downloadFile(path, name) } catch (e) { setDlError(errorMessage(e, 'Export failed. Please try again.')) }
  }
  const params = { q, status, page, page_size: 15, sort: 'score' }
  const leads = useQuery({ queryKey: ['leads', params], queryFn: async () => (await api.get('/leads', { params })).data, placeholderData: (p) => p })
  const data = leads.data
  const columns = [companyCol, contactCol, regionCol, { key: 'status', label: 'Status', className: 'text-xs capitalize' }, { key: 'tier', label: 'Tier', render: (l) => <TierPill tier={l.tier} /> }]
  return (
    <div className="grid gap-6 xl:grid-cols-5">
      <div className="space-y-3 xl:col-span-2">
        <div className="flex gap-2"><button className="btn-secondary" onClick={() => download('/crm/export?format=csv', 'leads.csv')}><Download className="h-4 w-4" /> CSV</button><button className="btn-secondary" onClick={() => download('/crm/export?format=xlsx', 'ai-outreach-report.xlsx')}><FileSpreadsheet className="h-4 w-4" /> Excel report</button></div>
        {dlError && <Notice kind="error">{dlError}</Notice>}
        <Card>
          <Filters q={q} setQ={(v) => { setQ(v); setPage(1) }} extra={<select className="input !w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} aria-label="Status filter"><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>} />
          <div className="mt-4"><LeadTable leads={data?.items ?? []} columns={columns} onRowClick={(l) => setSel(l.id)} selectedId={sel} empty="No leads match." /></div>
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} setPage={setPage} />}
        </Card>
      </div>
      <div className="xl:col-span-3">{sel ? <Profile key={sel} id={sel} onDeleted={() => setSel(null)} /> : <Card><Empty>Select a lead to see their profile, history and notes.</Empty></Card>}</div>
    </div>
  )
}
