import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clapperboard, ExternalLink, Info, Trash2, UserRound } from 'lucide-react'
import api from '../api/client'
import { Card, Empty, ErrorNotice, LeadPicker, Notice, Spinner, StatusPill, copyText } from '../components/ui'

function Cover({ id }) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    let url
    api.get(`/videos/${id}/cover.svg`, { responseType: 'blob' }).then((r) => { url = URL.createObjectURL(r.data); setSrc(url) }).catch(() => {})
    return () => url && URL.revokeObjectURL(url)
  }, [id])
  return src ? <a href={src} download={`cover-${id}.svg`} title="Download cover image"><img src={src} alt="Video cover" className="w-full rounded-xl" /></a> : null
}

function VideoCard({ video, checklist }) {
  const qc = useQueryClient()
  const [script, setScript] = useState(video.script)
  const [description, setDescription] = useState(video.description)
  const [link, setLink] = useState(video.loom_url)
  const [views, setViews] = useState(video.views ?? '')
  const refresh = () => qc.invalidateQueries({ queryKey: ['videos'] })
  const saveText = useMutation({ mutationFn: async () => api.patch(`/videos/${video.id}`, { script, description }), onSuccess: refresh })
  const saveLink = useMutation({ mutationFn: async () => api.patch(`/videos/${video.id}/link`, { loom_url: link }), onSuccess: refresh })
  const saveViews = useMutation({ mutationFn: async () => api.patch(`/videos/${video.id}/views`, { views: +views }), onSuccess: refresh })
  const del = useMutation({ mutationFn: async () => api.delete(`/videos/${video.id}`), onSuccess: refresh })
  const words = script.replace(/\[[^\]]*\]/g, '').trim().split(/\s+/).filter(Boolean).length
  const secs = Math.round((words / 150) * 60)

  return (
    <Card title={video.company_name} action={<StatusPill status={video.status === 'published' ? 'running' : 'paused'} />}>
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-3 lg:col-span-3">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>About {words} spoken words, roughly {secs} seconds{secs < 55 || secs > 95 ? ' (aim for 60 to 90)' : ''}</span>
            <button className="underline" onClick={() => copyText(script)}>Copy script</button>
          </div>
          <textarea className="input min-h-[320px] text-[13px] leading-relaxed" value={script} onChange={(e) => setScript(e.target.value)} aria-label="Script" />
          <p className="text-xs text-slate-500">Text in [BRACKETS] is a cue for you: show your screen, or add your own idea. Don't read it aloud.</p>
          <label className="label" htmlFor={`d${video.id}`}>Description (for the email)</label>
          <textarea id={`d${video.id}`} className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          <button className="btn-secondary" onClick={() => saveText.mutate()} disabled={saveText.isPending}>Save script</button>
        </div>
        <div className="space-y-4 lg:col-span-2">
          <Cover id={video.id} />
          {checklist && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Recording checklist</h3>
              <ol className="space-y-1.5 text-sm">{checklist.map((s, i) => (
                <li key={i} className="flex gap-2"><span className="mt-0.5 shrink-0 text-slate-400">{i + 1}.</span><span>{s.step}{s.requires_user && <UserRound className="ml-1 inline h-3.5 w-3.5 text-brand-600" title="You do this step" />}</span></li>))}</ol>
            </div>
          )}
          <div>
            <label className="label" htmlFor={`l${video.id}`}>Loom share link</label>
            <div className="flex gap-2"><input id={`l${video.id}`} className="input" placeholder="https://www.loom.com/share/…" value={link} onChange={(e) => setLink(e.target.value)} /><button className="btn-primary shrink-0" disabled={!link || saveLink.isPending} onClick={() => saveLink.mutate()}>Save</button></div>
            {video.loom_url && <a className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 dark:text-brand-300" href={video.loom_url} target="_blank" rel="noreferrer noopener">Open video <ExternalLink className="h-3 w-3" /></a>}
          </div>
          <div>
            <label className="label" htmlFor={`v${video.id}`}>Views (optional, you enter this from Loom)</label>
            <div className="flex gap-2"><input id={`v${video.id}`} type="number" min="0" className="input" value={views} onChange={(e) => setViews(e.target.value)} /><button className="btn-secondary shrink-0" disabled={views === '' || saveViews.isPending} onClick={() => saveViews.mutate()}>Save</button></div>
          </div>
          <ErrorNotice error={saveLink.error ?? saveViews.error ?? saveText.error} />
          <button className="btn-danger" onClick={() => window.confirm('Delete this video record?') && del.mutate()}><Trash2 className="h-4 w-4" /> Delete</button>
        </div>
      </div>
    </Card>
  )
}

export default function VideoStudio() {
  const qc = useQueryClient()
  const [lead, setLead] = useState(null)
  const [lastChecklist, setLastChecklist] = useState({})
  const caps = useQuery({ queryKey: ['video-caps'], queryFn: async () => (await api.get('/videos/capabilities')).data })
  const videos = useQuery({ queryKey: ['videos', 'all'], queryFn: async () => (await api.get('/videos')).data })
  const gen = useMutation({
    mutationFn: async () => (await api.post('/videos/script', { lead_id: lead.id })).data,
    onSuccess: (v) => { setLastChecklist((c) => ({ ...c, [v.id]: v.checklist })); qc.invalidateQueries({ queryKey: ['videos'] }) },
  })
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Create a video script" className="lg:col-span-1">
          <div className="space-y-3">
            <LeadPicker value={lead} onChange={setLead} />
            <button className="btn-primary w-full" disabled={!lead || gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? <Spinner /> : <Clapperboard className="h-4 w-4" />} Generate script</button>
            <ErrorNotice error={gen.error} />
          </div>
        </Card>
        <Card title="How this works" className="lg:col-span-2">
          <ol className="grid gap-2 sm:grid-cols-5">{(caps.data?.workflow ?? []).map((s, i) => <li key={s} className="rounded-xl bg-slate-50 p-3 text-xs dark:bg-white/5"><span className="mb-1 block font-semibold text-brand-600 dark:text-brand-300">{i + 1}</span>{s}</li>)}</ol>
          <div className="mt-3 space-y-1.5">{(caps.data?.notes ?? []).map((n) => <p key={n} className="flex gap-2 text-xs text-slate-500"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />{n}</p>)}</div>
        </Card>
      </div>
      <Notice>Researching the lead first (Lead Research) gives the script real details about their business to mention.</Notice>
      {videos.isLoading ? <Spinner /> : videos.data?.length === 0 ? <Card><Empty>No video scripts yet.</Empty></Card> : videos.data.map((v) => <VideoCard key={v.id + (v.loom_url || '')} video={v} checklist={lastChecklist[v.id]} />)}
    </div>
  )
}
