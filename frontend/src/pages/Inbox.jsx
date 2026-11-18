import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCheck, RefreshCw, Send } from 'lucide-react'
import api from '../api/client'
import { Card, Empty, ErrorNotice, Notice, Spinner, fmtDate } from '../components/ui'

const LABELS = ['interested', 'meeting_requested', 'need_more_information', 'follow_up_later', 'not_interested', 'out_of_office']
const LABEL_STYLE = {
  interested: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  meeting_requested: 'bg-brand-600 text-white',
  need_more_information: 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300',
  follow_up_later: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  not_interested: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300',
  out_of_office: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
}
const Label = ({ label }) => label ? <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${LABEL_STYLE[label]}`}>{label.replace(/_/g, ' ')}</span> : null

function Detail({ msg }) {
  const qc = useQueryClient()
  const [reply, setReply] = useState(msg.suggested_response)
  const [subject, setSubject] = useState(msg.subject.startsWith('Re:') ? msg.subject : `Re: ${msg.subject}`)
  useEffect(() => { setReply(msg.suggested_response) }, [msg.suggested_response])
  const refresh = () => qc.invalidateQueries({ queryKey: ['inbox'] })
  const classify = useMutation({ mutationFn: async (label) => (await api.post(`/inbox/${msg.id}/classify`, { label })).data, onSuccess: refresh })
  const reviewed = useMutation({ mutationFn: async () => api.post(`/inbox/${msg.id}/reviewed`), onSuccess: refresh })
  const send = useMutation({ mutationFn: async () => (await api.post(`/inbox/${msg.id}/reply`, { subject, body: reply, confirm: true })).data, onSuccess: refresh })
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="font-semibold">{msg.company_name}</h2><p className="text-xs text-slate-500">{msg.contact_name} · {msg.email} · {fmtDate(msg.received_at)}</p></div>
        <div className="flex items-center gap-2">
          <Label label={msg.label} />
          <select className="input !w-auto !py-1.5 text-xs" value="" onChange={(e) => e.target.value && classify.mutate(e.target.value)} aria-label="Change category"><option value="">Change category…</option>{LABELS.map((l) => <option key={l} value={l}>{l.replace(/_/g, ' ')}</option>)}</select>
        </div>
      </div>
      <h3 className="mt-4 text-sm font-semibold">{msg.subject}</h3>
      <p className="mt-1 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm dark:bg-white/5">{msg.body || '(empty message)'}</p>
      <p className="mt-1 text-xs text-slate-500">Category confidence {Math.round((msg.confidence ?? 0) * 100)}%. {msg.confidence < 0.5 && 'Low confidence: please check it yourself.'}</p>

      <div className="mt-5">
        <h3 className="mb-2 text-sm font-semibold">Reply</h3>
        {msg.label === 'out_of_office' && !reply ? <p className="text-sm text-slate-500">This is an auto-reply. No answer is suggested; your sequence keeps going.</p> : (
          <div className="space-y-2">
            <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Reply subject" />
            <textarea className="input min-h-[180px] font-mono text-[13px]" value={reply} onChange={(e) => setReply(e.target.value)} aria-label="Reply body" />
            <p className="text-xs text-slate-500">Suggested text is a starting point and is never sent automatically. Replace anything in [BRACKETS] first.</p>
            <div className="flex flex-wrap gap-2">
              <button className="btn-primary" disabled={send.isPending || !reply.trim()} onClick={() => window.confirm(`Send this reply to ${msg.email}?`) && send.mutate()}>{send.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Approve and send</button>
              <button className="btn-secondary" onClick={() => reviewed.mutate()} disabled={msg.reviewed}><CheckCheck className="h-4 w-4" /> {msg.reviewed ? 'Reviewed' : 'Mark reviewed'}</button>
            </div>
          </div>
        )}
        <div className="mt-2 space-y-2"><ErrorNotice error={send.error ?? classify.error} />{send.isSuccess && <Notice kind="ok">Reply sent.</Notice>}</div>
      </div>
    </Card>
  )
}

export default function Inbox() {
  const qc = useQueryClient()
  const [label, setLabel] = useState('')
  const [sel, setSel] = useState(null)
  const [note, setNote] = useState(null)
  const list = useQuery({ queryKey: ['inbox', label], queryFn: async () => (await api.get('/inbox', { params: { label } })).data })
  const sync = useMutation({
    mutationFn: async () => (await api.post('/inbox/sync', {})).data,
    onSuccess: (r) => { setNote(`Checked ${r.checked} recent emails: ${r.replies} repl${r.replies === 1 ? 'y' : 'ies'}, ${r.bounces} bounce(s), ${r.opt_outs} opt-out(s).`); qc.invalidateQueries({ queryKey: ['inbox'] }); qc.invalidateQueries({ queryKey: ['dashboard'] }) },
  })
  const items = list.data ?? []
  const current = items.find((m) => m.id === sel) ?? null
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled={sync.isPending} onClick={() => sync.mutate()}>{sync.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />} Check for replies</button>
        <select className="input !w-auto" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Filter"><option value="">All replies</option>{LABELS.map((l) => <option key={l} value={l}>{l.replace(/_/g, ' ')}</option>)}</select>
      </div>
      <ErrorNotice error={sync.error} />
      <Notice kind="ok">{note}</Notice>
      <Notice>Reads your mailbox over IMAP without changing anything (read-only). Only replies from people already in your leads are stored; other email is ignored. Bounce notices mark the address invalid and suppress it.</Notice>
      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-2">
          {list.isLoading ? <Spinner /> : items.length === 0 ? <Empty>No replies yet. Click "Check for replies" after sending.</Empty> : (
            <ul className="-mx-2 space-y-0.5">{items.map((m) => (
              <li key={m.id}><button onClick={() => setSel(m.id)} className={`w-full rounded-xl px-3 py-2.5 text-left transition hover:bg-slate-50 dark:hover:bg-white/5 ${sel === m.id ? 'bg-brand-50 dark:bg-brand-900/20' : ''}`}>
                <div className="flex items-center justify-between gap-2"><span className={`text-sm ${m.reviewed ? '' : 'font-semibold'}`}>{m.company_name}</span><Label label={m.label} /></div>
                <div className="truncate text-xs text-slate-500">{m.subject}</div><div className="text-[11px] text-slate-400">{fmtDate(m.received_at)}</div>
              </button></li>))}</ul>
          )}
        </Card>
        <div className="xl:col-span-3">{current ? <Detail key={current.id} msg={current} /> : <Card><Empty>Select a reply.</Empty></Card>}</div>
      </div>
    </div>
  )
}
