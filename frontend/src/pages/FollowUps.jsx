import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Sparkles } from 'lucide-react'
import api from '../api/client'
import { Card, Empty, ErrorNotice, Notice, Spinner, StatusPill, fmtDate } from '../components/ui'

function DraftBox({ draft, lead, onDone }) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const send = useMutation({
    mutationFn: async () => {
      await api.patch(`/emails/drafts/${draft.id}`, { subject, body })
      return (await api.post(`/emails/drafts/${draft.id}/send`, { confirm: true })).data
    },
    onSuccess: onDone,
  })
  return (
    <div className="mt-3 space-y-2 rounded-xl border border-brand-200 bg-brand-50/40 p-3 dark:border-brand-800 dark:bg-brand-900/10">
      <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
      <textarea className="input min-h-[160px] font-mono text-[13px]" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Body" />
      <button className="btn-primary" disabled={send.isPending} onClick={() => window.confirm(`Send this follow-up to ${lead.email}?`) && send.mutate()}>
        {send.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Approve and send
      </button>
      <ErrorNotice error={send.error} />
    </div>
  )
}

export default function FollowUps() {
  const qc = useQueryClient()
  const [drafts, setDrafts] = useState({})
  const [done, setDone] = useState(null)
  const due = useQuery({ queryKey: ['followups'], queryFn: async () => (await api.get('/followups/due')).data })
  const gen = useMutation({
    mutationFn: async (lead_id) => ({ lead_id, draft: (await api.post('/followups/generate', { lead_id })).data }),
    onSuccess: ({ lead_id, draft }) => setDrafts((d) => ({ ...d, [lead_id]: draft })),
  })
  const d = due.data
  return (
    <div className="space-y-6">
      <Notice>Follow-ups stop automatically when a lead replies, bounces or unsubscribes. An out-of-office auto-reply does not stop a sequence. Suggested times are a simple rule (Tuesday to Thursday, 10:00 UTC), not a prediction.</Notice>
      <Notice kind="ok">{done}</Notice>
      <Card title="Scheduled in running campaigns">
        {due.isLoading ? <Spinner /> : d.scheduled.length === 0 ? <Empty>No follow-ups scheduled. Start a campaign with follow-up intervals.</Empty> : (
          <div className="-mx-5 overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm">
            <thead><tr className="border-b border-slate-200/70 text-xs uppercase text-slate-500 dark:border-white/5">{['Lead', 'Campaign', 'Sent so far', 'Next email'].map((h) => <th key={h} className="px-5 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{d.scheduled.map((s) => (
              <tr key={`${s.campaign_id}-${s.lead_id}`} className="border-b border-slate-100 last:border-0 dark:border-white/5">
                <td className="px-5 py-2.5 font-medium">{s.company_name}</td><td className="px-5 py-2.5 text-xs">{s.campaign} <StatusPill status={s.campaign_status} /></td>
                <td className="px-5 py-2.5 text-xs">{s.step} of {s.of + 1}</td>
                <td className="px-5 py-2.5 text-xs">{fmtDate(s.next_send_at)}{s.overdue && <span className="ml-1 text-amber-600">due</span>}</td>
              </tr>))}</tbody></table></div>
        )}
      </Card>
      <Card title="Unanswered, no sequence running">
        <p className="mb-3 text-xs text-slate-500">{d?.rule}</p>
        {due.isLoading ? <Spinner /> : d.needs_followup.length === 0 ? <Empty>Nobody is waiting for a follow-up.</Empty> : (
          <ul className="space-y-3">{d.needs_followup.map((n) => (
            <li key={n.lead_id} className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><div className="font-medium">{n.company_name}</div><div className="text-xs text-slate-500">{n.contact_name} · {n.email} · {n.emails_sent} email(s) sent · waiting {n.days_waiting} days</div><div className="text-xs text-slate-500">Suggested send: {fmtDate(n.suggested_send_at)}</div></div>
                <button className="btn-secondary" disabled={gen.isPending} onClick={() => gen.mutate(n.lead_id)}>{gen.isPending && gen.variables === n.lead_id ? <Spinner /> : <Sparkles className="h-4 w-4" />} Draft follow-up</button>
              </div>
              {drafts[n.lead_id] && <DraftBox draft={drafts[n.lead_id]} lead={n} onDone={() => { setDone(`Follow-up sent to ${n.company_name}.`); setDrafts((x) => ({ ...x, [n.lead_id]: undefined })); qc.invalidateQueries({ queryKey: ['followups'] }) }} />}
            </li>))}</ul>
        )}
        <ErrorNotice error={gen.error} />
      </Card>
    </div>
  )
}
