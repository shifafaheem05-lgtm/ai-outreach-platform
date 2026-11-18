import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, SendHorizontal } from 'lucide-react'
import api from '../api/client'
import { Card, ErrorNotice, Notice, Spinner, fmtDate } from '../components/ui'

const EXAMPLES = [
  'Research my top 3 leads',
  'Score my leads',
  'Generate personalized cold emails for my top 10 leads',
  'Create Loom video scripts for my top 20 leads',
  'Prepare a follow-up campaign',
  'Show my best-performing campaign',
  'Find marketing agencies in USA',
]

export default function Assistant() {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const runs = useQuery({ queryKey: ['assistant-runs'], queryFn: async () => (await api.get('/assistant/runs')).data })
  const run = useMutation({
    mutationFn: async (command) => (await api.post('/assistant/command', { command })).data,
    onSuccess: () => { setText(''); qc.invalidateQueries({ queryKey: ['assistant-runs'] }); qc.invalidateQueries({ queryKey: ['leads'] }); qc.invalidateQueries({ queryKey: ['campaigns'] }) },
  })
  const go = (c) => c.trim() && !run.isPending && run.mutate(c)
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300"><Bot className="h-5 w-5" /></div><div><h2 className="font-semibold">Outreach assistant</h2><p className="text-xs text-slate-500">Type a command. It prepares work; it never sends email.</p></div></div>
        <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); go(text) }}>
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Research my top 3 leads" aria-label="Command" />
          <button className="btn-primary shrink-0" disabled={run.isPending || !text.trim()} aria-label="Run command">{run.isPending ? <Spinner /> : <SendHorizontal className="h-4 w-4" />}</button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">{EXAMPLES.map((e) => <button key={e} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 transition hover:bg-slate-50 dark:border-white/10 dark:text-slate-300 dark:hover:bg-white/5" onClick={() => go(e)} disabled={run.isPending}>{e}</button>)}</div>
        {run.isPending && <p className="mt-3 text-sm text-slate-500">Working… researching websites can take up to a minute.</p>}
        <div className="mt-3"><ErrorNotice error={run.error} /></div>
      </Card>
      <Notice>Anything that contacts a prospect goes through Email Campaigns: you review the drafts, submit for approval, and a manager approves and starts it. The assistant understands the example commands above; it does not search the web for new businesses (import a CSV for that).</Notice>
      {(runs.data ?? []).map((r) => (
        <Card key={r.id}>
          <div className="flex justify-between gap-3 text-xs text-slate-500"><span className="font-medium text-slate-800 dark:text-slate-200">“{r.command}”</span><span>{fmtDate(r.created_at)}</span></div>
          <p className="mt-2 text-sm">{r.message}</p>
          {r.steps?.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">{r.steps.map((s) => <li key={s}>{s}</li>)}</ul>}
          {r.intent === 'search' && r.data?.length > 0 && <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">{r.data.slice(0, 20).map((l) => <li key={l.id} className="rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-white/5">{l.company} <span className="text-slate-500">· {l.industry || 'n/a'} · {l.tier} {l.score}</span></li>)}</ul>}
        </Card>
      ))}
    </div>
  )
}
