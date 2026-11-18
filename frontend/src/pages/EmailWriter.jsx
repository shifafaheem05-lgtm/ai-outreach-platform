import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Copy, Send, Sparkles, Video } from 'lucide-react'
import api from '../api/client'
import { Card, ErrorNotice, LeadPicker, Notice, Spinner, copyText } from '../components/ui'

const TONES = ['professional', 'friendly', 'direct', 'casual', 'consultative']

function Variant({ draft, lead, videos }) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [note, setNote] = useState(null)
  const [videoId, setVideoId] = useState('')
  const save = useMutation({ mutationFn: async () => (await api.patch(`/emails/drafts/${draft.id}`, { subject, body })).data, onSuccess: () => setNote('Saved.') })
  const insert = useMutation({
    mutationFn: async () => { await save.mutateAsync(); return (await api.post(`/emails/drafts/${draft.id}/insert-video`, { video_id: +videoId })).data },
    onSuccess: (d) => { setBody(d.body); setNote('Video link placeholder added; the real Loom link is filled in when sending.') },
  })
  const send = useMutation({
    mutationFn: async () => { await save.mutateAsync(); return (await api.post(`/emails/drafts/${draft.id}/send`, { confirm: true })).data },
    onSuccess: () => setNote('Sent.'),
  })
  const words = body.trim().split(/\s+/).length
  return (
    <Card title={<span className="capitalize">{draft.variant}</span>} action={<span className="text-xs text-slate-500">{words} words{draft.ai ? ' · AI written' : ' · template'}</span>}>
      <div className="space-y-2">
        <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
        <textarea className="input min-h-[240px] font-mono text-[13px]" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Body" />
        {videos.length > 0 && (
          <div className="flex gap-2">
            <select className="input" value={videoId} onChange={(e) => setVideoId(e.target.value)} aria-label="Video"><option value="">Add a Loom video…</option>{videos.filter((v) => v.loom_url).map((v) => <option key={v.id} value={v.id}>{v.loom_url}</option>)}</select>
            <button className="btn-secondary shrink-0" disabled={!videoId || insert.isPending} onClick={() => insert.mutate()}><Video className="h-4 w-4" /> Add</button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-secondary" onClick={() => save.mutate()} disabled={save.isPending}>Save</button>
          <button className="btn-secondary" onClick={() => copyText(`Subject: ${subject}\n\n${body}`)}><Copy className="h-4 w-4" /> Copy</button>
          <button className="btn-primary" disabled={send.isPending || !lead.email}
            onClick={() => window.confirm(`Send this email to ${lead.email} now?\n\nIt will include your postal address and an unsubscribe link.`) && send.mutate()}>
            {send.isPending ? <Spinner /> : <Send className="h-4 w-4" />} Send now
          </button>
        </div>
        <ErrorNotice error={save.error ?? insert.error ?? send.error} />
        <Notice kind="ok">{note}</Notice>
      </div>
    </Card>
  )
}

export default function EmailWriter() {
  const [lead, setLead] = useState(null)
  const [tone, setTone] = useState('professional')
  const caps = useQuery({ queryKey: ['lead-caps'], queryFn: async () => (await api.get('/leads/capabilities')).data })
  const videos = useQuery({ queryKey: ['videos', lead?.id], enabled: !!lead, queryFn: async () => (await api.get('/videos', { params: { lead_id: lead.id } })).data })
  const gen = useMutation({ mutationFn: async () => (await api.post('/emails/generate', { lead_id: lead.id, tone })).data })

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="space-y-4">
        <Card title="Write emails">
          <div className="space-y-3">
            <LeadPicker value={lead} onChange={(l) => { setLead(l); gen.reset() }} />
            <div><label className="label" htmlFor="tone">Tone</label><select id="tone" className="input" value={tone} onChange={(e) => setTone(e.target.value)}>{TONES.map((t) => <option key={t}>{t}</option>)}</select></div>
            <button className="btn-primary w-full" disabled={!lead || gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? <Spinner /> : <Sparkles className="h-4 w-4" />} Generate 3 versions</button>
            <ErrorNotice error={gen.error} />
          </div>
        </Card>
        <Notice>{caps.data?.llm.configured ? `AI writing is on (${caps.data.llm.model}).` : 'No AI model is configured, so emails come from a personalised template using only facts stored for the lead. Add a free API key in .env for AI-written emails.'} Research a lead first for more specific emails. Nothing is sent automatically.</Notice>
      </div>
      <div className="space-y-4 xl:col-span-2">
        {gen.data ? gen.data.map((d) => <Variant key={d.id} draft={d} lead={lead} videos={videos.data ?? []} />) : <Card><p className="py-12 text-center text-sm text-slate-500">Pick a lead and generate short, medium and detailed versions with different subject lines.</p></Card>}
      </div>
    </div>
  )
}
