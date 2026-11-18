import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, Pause, Play, Plus, Send, Undo2, X, Zap } from 'lucide-react'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Card, Empty, ErrorNotice, Notice, Spinner, StatusPill, fmtDate } from '../components/ui'

const TONES = ['professional', 'friendly', 'direct', 'casual', 'consultative']

function NewCampaign({ onCreated }) {
  const qc = useQueryClient()
  const mailboxes = useQuery({ queryKey: ['integrations'], queryFn: async () => (await api.get('/integrations')).data })
  const [form, setForm] = useState({ name: '', tone: 'professional', sender_integration_id: '', intervals: '3, 7', start_hour: '', end_hour: '', weekdays_only: true })
  const create = useMutation({
    mutationFn: async () => {
      const schedule = { utc_offset_hours: -new Date().getTimezoneOffset() / 60, weekdays_only: form.weekdays_only }
      if (form.start_hour !== '' && form.end_hour !== '') Object.assign(schedule, { window_start: +form.start_hour, window_end: +form.end_hour })
      return (await api.post('/campaigns', {
        name: form.name, tone: form.tone, sender_integration_id: form.sender_integration_id ? +form.sender_integration_id : null,
        followup_intervals: form.intervals.split(',').map((x) => parseInt(x, 10)).filter((n) => n > 0), schedule,
      })).data
    },
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ['campaigns'] }); setForm({ ...form, name: '' }); onCreated(c.id) },
  })
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <div><label className="label" htmlFor="c-name">Name</label><input id="c-name" className="input" required value={form.name} onChange={set('name')} /></div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className="label" htmlFor="c-tone">Tone</label><select id="c-tone" className="input" value={form.tone} onChange={set('tone')}>{TONES.map((t) => <option key={t}>{t}</option>)}</select></div>
        <div><label className="label" htmlFor="c-int">Follow-ups after (days)</label><input id="c-int" className="input" value={form.intervals} onChange={set('intervals')} placeholder="3, 7" /></div>
      </div>
      <div>
        <label className="label" htmlFor="c-box">Sending mailbox</label>
        <select id="c-box" className="input" value={form.sender_integration_id} onChange={set('sender_integration_id')}>
          <option value="">Choose…</option>
          {(mailboxes.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.label} ({m.from_email})</option>)}
        </select>
        {mailboxes.data?.length === 0 && <p className="mt-1 text-xs text-amber-600">Add a mailbox in Integrations first.</p>}
      </div>
      <div className="grid grid-cols-3 items-end gap-3">
        <div><label className="label" htmlFor="c-s">Send from (hour)</label><input id="c-s" type="number" min="0" max="23" className="input" value={form.start_hour} onChange={set('start_hour')} placeholder="9" /></div>
        <div><label className="label" htmlFor="c-e">Until (hour)</label><input id="c-e" type="number" min="1" max="24" className="input" value={form.end_hour} onChange={set('end_hour')} placeholder="17" /></div>
        <label className="flex items-center gap-2 pb-3 text-sm"><input type="checkbox" checked={form.weekdays_only} onChange={set('weekdays_only')} /> Weekdays only</label>
      </div>
      <p className="text-xs text-slate-500">Send window uses your computer's current time zone.</p>
      <ErrorNotice error={create.error} />
      <button className="btn-primary" disabled={create.isPending}>{create.isPending ? <Spinner /> : <Plus className="h-4 w-4" />} Create campaign</button>
    </form>
  )
}

function DraftEditor({ draft, editable }) {
  const [open, setOpen] = useState(false)
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const save = useMutation({ mutationFn: async () => (await api.patch(`/emails/drafts/${draft.id}`, { subject, body })).data })
  return (
    <div className="rounded-xl border border-slate-200 dark:border-white/10">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        <span className="font-medium">{draft.step === 0 ? 'Initial email' : `Follow-up ${draft.step}`}</span>
        <span className="truncate text-slate-500">{subject}</span>
        <span className="ml-auto text-xs capitalize text-slate-400">{draft.status}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-100 p-3 dark:border-white/5">
          <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!editable} aria-label="Subject" />
          <textarea className="input min-h-[180px] font-mono text-[13px]" value={body} onChange={(e) => setBody(e.target.value)} disabled={!editable} aria-label="Body" />
          {editable ? (
            <div className="flex items-center gap-3">
              <button className="btn-secondary" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Spinner /> : 'Save changes'}</button>
              {save.isSuccess && <span className="text-xs text-emerald-600">Saved</span>}
              <ErrorNotice error={save.error} />
            </div>
          ) : (
            <p className="text-xs text-slate-500">Locked. Revert the campaign to draft to edit.</p>
          )}
          <p className="text-xs text-slate-500">The unsubscribe link and your postal address are added automatically when sending.</p>
        </div>
      )}
    </div>
  )
}

function Detail({ id }) {
  const qc = useQueryClient()
  const { user } = useAuth()
  const manager = ['manager', 'admin'].includes(user.role)
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState([])
  const [variant, setVariant] = useState('medium')
  const [msg, setMsg] = useState(null)
  const c = useQuery({ queryKey: ['campaign', id], queryFn: async () => (await api.get(`/campaigns/${id}`)).data })
  const drafts = useQuery({ queryKey: ['campaign-drafts', id], queryFn: async () => (await api.get(`/campaigns/${id}/drafts`)).data })
  const pool = useQuery({ queryKey: ['lead-pool', q], enabled: c.data?.status === 'draft', queryFn: async () => (await api.get('/leads', { params: { q, page_size: 40, sort: 'score' } })).data })
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: async () => (await api.get('/settings/readiness')).data })

  const refresh = () => ['campaign', 'campaigns', 'campaign-drafts', 'dashboard'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
  const act = useMutation({
    mutationFn: async ({ path, body }) => (await api.post(`/campaigns/${id}/${path}`, body ?? {})).data,
    onSuccess: (data, { path }) => {
      if (path === 'leads') setMsg(`Added ${data.added}${data.skipped.length ? `; skipped ${data.skipped.length} (${data.skipped.map((s) => `${s.company}: ${s.reason}`).join('; ')})` : ''}.`)
      else if (path === 'generate-drafts') setMsg(`Drafted emails for ${data.generated_for} lead(s)${data.remaining ? `; ${data.remaining} more, click again` : ''}.`)
      else setMsg(null)
      setPicked([])
      refresh()
    },
    onError: () => setMsg(null),
  })
  const process = useMutation({ mutationFn: async () => (await api.post('/campaigns/process-now')).data, onSuccess: (r) => { setMsg(`Sender ran: ${r.sent} sent, ${r.bounced} bounced, ${r.blocked} blocked, ${r.waiting} waiting.`); refresh() } })
  const del = useMutation({ mutationFn: async () => api.delete(`/campaigns/${id}`), onSuccess: () => { refresh(); window.location.reload() } })

  if (c.isLoading) return <Card><Spinner /></Card>
  const k = c.data
  const draftMode = k.status === 'draft'
  const byLead = (drafts.data ?? []).reduce((a, d) => ({ ...a, [d.company_name]: [...(a[d.company_name] ?? []), d] }), {})
  const btn = (label, path, Icon, cls = 'btn-secondary', confirmText) => (
    <button className={cls} disabled={act.isPending} onClick={() => (!confirmText || window.confirm(confirmText)) && act.mutate({ path })}>
      {act.isPending && act.variables?.path === path ? <Spinner /> : <Icon className="h-4 w-4" />} {label}
    </button>
  )

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2"><h2 className="text-lg font-semibold text-slate-900 dark:text-white">{k.name}</h2><StatusPill status={k.status} /></div>
            <p className="text-xs text-slate-500">{k.total_leads} leads · tone {k.tone} · follow-ups after {k.followup_intervals.join(', ') || 'none'} day(s)</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {draftMode && btn('Submit for approval', 'submit-approval', Send, 'btn-primary')}
            {k.status === 'pending_approval' && manager && <>{btn('Approve', 'approve', Check, 'btn-primary', 'Approve this campaign? Emails will be allowed to send once it is started.')}{btn('Reject', 'reject', X)}</>}
            {k.status === 'pending_approval' && !manager && <span className="self-center text-sm text-slate-500">Waiting for a manager to approve</span>}
            {['approved', 'paused'].includes(k.status) && manager && btn(k.status === 'paused' ? 'Resume' : 'Start sending', 'start', Play, 'btn-primary', 'Start sending to real recipients?')}
            {k.status === 'running' && manager && <>{btn('Pause', 'pause', Pause)}<button className="btn-secondary" disabled={process.isPending} onClick={() => process.mutate()}>{process.isPending ? <Spinner /> : <Zap className="h-4 w-4" />} Send due now</button></>}
            {['pending_approval', 'approved', 'paused'].includes(k.status) && btn('Revert to draft', 'revert', Undo2)}
            {draftMode && manager && <button className="btn-danger" onClick={() => window.confirm('Delete this campaign?') && del.mutate()}>Delete</button>}
          </div>
        </div>
        <div className="mt-3 space-y-2">
          <ErrorNotice error={act.error ?? process.error} />
          <Notice kind="ok">{msg}</Notice>
          {draftMode && readiness.data && !readiness.data.ready && (
            <Notice kind="info">Before you can send: {readiness.data.checks.filter((x) => !x.ok).map((x) => x.label).join('; ')}. See Settings and Integrations.</Notice>
          )}
          {k.status === 'running' && <Notice>The sender checks for due emails every minute, respects your hourly/daily limits and spaces emails out. Replies, bounces and opt-outs stop a lead's sequence.</Notice>}
        </div>
      </Card>

      {draftMode && (
        <Card title="1. Add leads">
          <input className="input mb-3" placeholder="Search leads…" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="max-h-56 overflow-y-auto rounded-xl border border-slate-200 dark:border-white/10">
            {(pool.data?.items ?? []).map((l) => (
              <label key={l.id} className="flex cursor-pointer items-center gap-3 border-b border-slate-100 px-3 py-2 text-sm last:border-0 dark:border-white/5">
                <input type="checkbox" checked={picked.includes(l.id)} onChange={(e) => setPicked(e.target.checked ? [...picked, l.id] : picked.filter((x) => x !== l.id))} />
                <span className="font-medium">{l.company_name}</span><span className="truncate text-xs text-slate-500">{l.email || 'no email'}</span>
                <span className="ml-auto text-xs text-slate-400">{l.tier} {l.score}</span>
              </label>
            ))}
          </div>
          <button className="btn-secondary mt-3" disabled={!picked.length || act.isPending} onClick={() => act.mutate({ path: 'leads', body: { lead_ids: picked } })}>Add {picked.length || ''} selected</button>
        </Card>
      )}

      {draftMode && (
        <Card title="2. Write the emails">
          <p className="mb-3 text-sm text-slate-500">Creates the initial email and each follow-up for every lead, using only what is known about them. You can edit every email below before submitting.</p>
          <div className="flex flex-wrap items-center gap-2">
            <select className="input w-auto" value={variant} onChange={(e) => setVariant(e.target.value)} aria-label="Email length"><option value="short">Short</option><option value="medium">Medium</option><option value="detailed">Detailed</option></select>
            <button className="btn-primary" disabled={!k.total_leads || act.isPending} onClick={() => act.mutate({ path: 'generate-drafts', body: { variant } })}>{act.isPending && act.variables?.path === 'generate-drafts' ? <Spinner /> : null} Generate drafts</button>
            <button className="btn-secondary" disabled={!k.total_leads || act.isPending} onClick={() => window.confirm('Replace all existing drafts?') && act.mutate({ path: 'generate-drafts', body: { variant, regenerate: true } })}>Regenerate all</button>
          </div>
        </Card>
      )}

      <Card title={`Leads (${k.total_leads})`}>
        {k.leads.length === 0 ? <Empty>No leads in this campaign yet.</Empty> : (
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead><tr className="border-b border-slate-200/70 text-xs uppercase text-slate-500 dark:border-white/5">{['Company', 'Email', 'State', 'Step', 'Next send'].map((h) => <th key={h} className="px-5 py-2 font-medium">{h}</th>)}</tr></thead>
              <tbody>{k.leads.map((l) => (
                <tr key={l.id} className="border-b border-slate-100 last:border-0 dark:border-white/5">
                  <td className="px-5 py-2.5 font-medium">{l.company_name}</td><td className="px-5 py-2.5 text-xs">{l.email}</td>
                  <td className="px-5 py-2.5 text-xs capitalize">{l.state.replace('_', ' ')}</td><td className="px-5 py-2.5 text-xs">{l.current_step}/{k.max_followups + 1}</td>
                  <td className="px-5 py-2.5 text-xs">{fmtDate(l.next_send_at)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Emails in this campaign">
        {Object.keys(byLead).length === 0 ? <Empty>No drafts yet.</Empty> : (
          <div className="space-y-4">{Object.entries(byLead).map(([company, list]) => (
            <div key={company}><h3 className="mb-1.5 text-sm font-semibold">{company}</h3><div className="space-y-1.5">{list.map((d) => <DraftEditor key={d.id + d.status} draft={d} editable={draftMode} />)}</div></div>
          ))}</div>
        )}
      </Card>
    </div>
  )
}

export default function Campaigns() {
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const list = useQuery({ queryKey: ['campaigns'], queryFn: async () => (await api.get('/campaigns')).data })
  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="space-y-4">
        <Card title="Campaigns" action={<button className="btn-secondary !px-3 !py-1.5" onClick={() => setCreating(!creating)}><Plus className="h-4 w-4" /> New</button>}>
          {creating && <div className="mb-4 border-b border-slate-100 pb-4 dark:border-white/5"><NewCampaign onCreated={(id) => { setSelected(id); setCreating(false) }} /></div>}
          {list.isLoading ? <Spinner /> : list.data?.length === 0 ? <Empty>No campaigns yet. Create one to start.</Empty> : (
            <ul className="space-y-1">{list.data.map((c) => (
              <li key={c.id}>
                <button onClick={() => setSelected(c.id)} className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-left text-sm transition hover:bg-slate-50 dark:hover:bg-white/5 ${selected === c.id ? 'bg-brand-50 dark:bg-brand-900/20' : ''}`}>
                  <span><span className="block font-medium">{c.name}</span><span className="text-xs text-slate-500">{c.total_leads} leads</span></span><StatusPill status={c.status} />
                </button>
              </li>))}</ul>
          )}
        </Card>
        <Notice>Nothing is sent until a manager approves the campaign and starts it. Every email includes your postal address and a one-click unsubscribe link, and suppressed addresses are skipped at send time.</Notice>
      </div>
      <div className="xl:col-span-2">{selected ? <Detail key={selected} id={selected} /> : <Card><Empty>Select or create a campaign.</Empty></Card>}</div>
    </div>
  )
}
