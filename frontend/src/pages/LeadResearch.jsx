import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, FileSearch, Info, Loader2 } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import LeadTable, { Filters, Pager, Pill, companyCol } from '../components/LeadTable'

function Section({ title, text }) {
  if (!text) return null
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-slate-700 dark:text-slate-300">{text}</p>
    </div>
  )
}

function Report({ lead }) {
  const qc = useQueryClient()
  const report = useQuery({
    queryKey: ['research', lead.id],
    queryFn: async () => (await api.get(`/leads/${lead.id}/research`)).data,
    retry: false,
  })
  const run = useMutation({
    mutationFn: async () => (await api.post(`/leads/${lead.id}/research`)).data,
    onSuccess: (data) => {
      qc.setQueryData(['research', lead.id], data)
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
  })
  const r = report.data

  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-slate-900 dark:text-white">{lead.company_name}</h2>
          {lead.website ? (
            <a href={lead.website} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline dark:text-brand-300">
              {lead.website} <ExternalLink className="h-3 w-3" />
            </a>
          ) : (
            <span className="text-xs text-slate-500">No website on this lead</span>
          )}
        </div>
        <button className="btn-primary shrink-0" disabled={!lead.website || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
          {r ? 'Re-run' : 'Research'}
        </button>
      </div>

      {run.isPending && <p className="text-sm text-slate-500">Reading the website politely (robots.txt, small delays between pages). This can take 10 to 30 seconds.</p>}
      {run.isError && <p role="alert" className="text-sm text-red-600">{errorMessage(run.error)}</p>}
      {report.isLoading && <p className="text-sm text-slate-500">Loading&hellip;</p>}
      {!r && !report.isLoading && !run.isPending && <p className="text-sm text-slate-500">No research yet for this lead.</p>}

      {r && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Pill className="bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300">{r.model === 'none' ? 'no data' : r.model}</Pill>
            <span>{new Date(r.created_at).toLocaleString()}</span>
          </div>
          <Section title="Summary" text={r.summary} />
          <Section title="Products & services" text={r.products_services} />
          <Section title="Possible pain points" text={r.pain_points} />
          <Section title="Opportunities for us" text={r.opportunities} />
          {r.sources.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sources (pages read)</h3>
              <ul className="mt-1 space-y-1">
                {r.sources.map((s) => (
                  <li key={s.url} className="text-xs">
                    <a href={s.url} target="_blank" rel="noreferrer noopener" className="text-brand-600 hover:underline dark:text-brand-300">{s.title || s.url}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function LeadResearch() {
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)
  const params = { q, page, page_size: 12 }
  const leads = useQuery({ queryKey: ['leads', params], queryFn: async () => (await api.get('/leads', { params })).data, placeholderData: (p) => p })
  const caps = useQuery({ queryKey: ['lead-caps'], queryFn: async () => (await api.get('/leads/capabilities')).data })
  const data = leads.data

  const columns = [
    companyCol,
    { key: 'researched', label: 'Report', render: (l) => (l.researched ? <Pill className="bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">done</Pill> : <span className="text-xs text-slate-400">—</span>) },
  ]

  return (
    <div className="space-y-4">
      {caps.data && !caps.data.llm.configured && (
        <div className="flex gap-3 rounded-xl bg-brand-50 p-4 text-sm text-brand-900 dark:bg-brand-900/20 dark:text-brand-100">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            No AI model is configured, so reports list what the website says (title, description, headings) but do not infer pain points or opportunities. Add a free API key (Groq, Google Gemini, or a local Ollama) in <code>.env</code> and restart to turn on AI analysis. See <code>.env.example</code>.
          </p>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-5">
        <div className="card xl:col-span-2">
          <Filters q={q} setQ={(v) => { setQ(v); setPage(1) }} />
          <div className="mt-4">
            <LeadTable leads={data?.items ?? []} columns={columns} onRowClick={setSelected} selectedId={selected?.id} empty="No leads yet. Add some in Lead Discovery." />
          </div>
          {data && <Pager page={data.page} pageSize={data.page_size} total={data.total} setPage={setPage} />}
        </div>
        <div className="xl:col-span-3">
          {selected ? (
            <Report key={selected.id} lead={selected} />
          ) : (
            <div className="card py-16 text-center text-sm text-slate-500">Select a lead to view or run its research report.</div>
          )}
        </div>
      </div>
    </div>
  )
}
