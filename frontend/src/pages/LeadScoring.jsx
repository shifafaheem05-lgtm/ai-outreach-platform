import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Sparkles } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import LeadTable, { TierPill, companyCol, contactCol } from '../components/LeadTable'
import StatCard from '../components/StatCard'

export default function LeadScoring() {
  const qc = useQueryClient()
  const [targets, setTargets] = useState('')
  const summary = useQuery({ queryKey: ['scoring'], queryFn: async () => (await api.get('/scoring/summary')).data })
  const run = useMutation({
    mutationFn: async () =>
      (await api.post('/scoring/run', { target_industries: targets.split(',').map((t) => t.trim()).filter(Boolean) })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['scoring'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const s = summary.data

  const columns = [
    companyCol,
    contactCol,
    {
      key: 'score',
      label: 'Score',
      render: (l) => (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100 dark:bg-white/10">
            <div className="h-full rounded-full bg-gradient-to-r from-brand-400 to-brand-700" style={{ width: `${l.score}%` }} />
          </div>
          <span className="w-7 text-right text-sm font-medium text-slate-900 dark:text-white">{l.score}</span>
        </div>
      ),
    },
    { key: 'tier', label: 'Tier', render: (l) => <TierPill tier={l.tier} /> },
  ]

  return (
    <div className="space-y-6">
      <div className="card">
        <h2 className="font-semibold text-slate-900 dark:text-white">Score your leads</h2>
        <p className="mt-1 text-sm text-slate-500">
          Rules-based score from 0 to 100: contact seniority, email quality, company size, industry match, website, research done and replies. Hot is 70+, Warm 40 to 69, Cold below 40.
        </p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div className="min-w-[240px] flex-1">
            <label className="label" htmlFor="targets">Industries you target (optional, comma separated)</label>
            <input id="targets" className="input" placeholder="marketing, saas, e-commerce" value={targets} onChange={(e) => setTargets(e.target.value)} />
          </div>
          <button className="btn-primary" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Run scoring
          </button>
        </div>
        {run.isError && <p role="alert" className="mt-3 text-sm text-red-600">{errorMessage(run.error)}</p>}
        {run.isSuccess && <p role="status" className="mt-3 text-sm text-emerald-700 dark:text-emerald-300">Scored {run.data.scored} leads.</p>}
      </div>

      {s && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Hot" value={s.tiers.hot} hint="Score 70+" />
            <StatCard label="Warm" value={s.tiers.warm} hint="Score 40 to 69" />
            <StatCard label="Cold" value={s.tiers.cold} hint="Below 40" />
            <StatCard label="Average score" value={s.average_score} hint={`Model: ${s.model}`} />
          </div>
          <div className="card">
            <h2 className="mb-3 font-semibold text-slate-900 dark:text-white">Top prospects</h2>
            <LeadTable leads={s.top_leads} columns={columns} empty="No leads yet. Add some in Lead Discovery, then run scoring." />
          </div>
        </>
      )}
    </div>
  )
}
