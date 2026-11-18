import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertCircle, CalendarCheck, CheckCircle2, MailCheck, MailX, MessageSquareReply, Send, Target, Users, Video } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import StatCard from '../components/StatCard'

const TIER_COLORS = { hot: '#7c3aed', warm: '#a78bfa', cold: '#cbd5e1' }
const STATUS_STYLES = {
  running: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  completed: 'bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300',
  draft: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  paused: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  pending_approval: 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-300',
}

const pct = (n) => `${n}%`
const shortDate = (d) => new Date(d + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

function Skeleton() {
  return (
    <div className="animate-pulse space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-28 rounded-2xl bg-slate-200/70 dark:bg-white/5" />
        ))}
      </div>
      <div className="h-80 rounded-2xl bg-slate-200/70 dark:bg-white/5" />
    </div>
  )
}

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => (await api.get('/dashboard/summary')).data,
  })

  if (isLoading) return <Skeleton />
  if (error)
    return (
      <div className="card flex items-center gap-3 text-red-600 dark:text-red-400">
        <AlertCircle className="h-5 w-5" /> {errorMessage(error, 'Could not load dashboard')}
      </div>
    )

  const tierData = Object.entries(data.leads_by_tier).map(([name, value]) => ({ name, value }))
  const tierTotal = tierData.reduce((s, t) => s + t.value, 0)
  const ve = data.video_engagement

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Leads discovered" value={data.total_leads} icon={Users} hint="All leads in your workspace" />
        <StatCard label="Qualified leads" value={data.qualified_leads} icon={Target} hint="Hot + Warm tier" />
        <StatCard label="Emails sent" value={data.emails_sent} icon={Send} />
        <StatCard label="Delivery rate" value={pct(data.delivery_rate)} icon={MailCheck} />
        <StatCard label="Bounce rate" value={pct(data.bounce_rate)} icon={MailX} />
        <StatCard label="Reply rate" value={pct(data.reply_rate)} icon={MessageSquareReply} hint="Of contacted leads" />
        <StatCard label="Positive responses" value={pct(data.positive_response_rate)} icon={CheckCircle2} hint="Of replies" />
        <StatCard label="Meetings generated" value={data.meetings_generated} icon={CalendarCheck} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="card xl:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900 dark:text-white">Email activity</h2>
            <span className="text-xs text-slate-500">Last 14 days</span>
          </div>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.activity} margin={{ left: -20, right: 8, top: 8 }}>
                <defs>
                  <linearGradient id="sent" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7c3aed" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#7c3aed" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.2} vertical={false} />
                <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
                <Tooltip
                  labelFormatter={shortDate}
                  contentStyle={{ borderRadius: 12, border: 'none', boxShadow: '0 8px 24px rgba(0,0,0,.15)' }}
                />
                <Area type="monotone" dataKey="sent" name="Sent" stroke="#7c3aed" strokeWidth={2.5} fill="url(#sent)" />
                <Area type="monotone" dataKey="replies" name="Replies" stroke="#10b981" strokeWidth={2.5} fill="transparent" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h2 className="mb-2 font-semibold text-slate-900 dark:text-white">Lead tiers</h2>
          {tierTotal === 0 ? (
            <p className="py-16 text-center text-sm text-slate-500">No leads yet. Import some in Lead Discovery.</p>
          ) : (
            <>
              <div className="relative h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={tierData} dataKey="value" innerRadius={58} outerRadius={82} paddingAngle={3} stroke="none">
                      {tierData.map((t) => (
                        <Cell key={t.name} fill={TIER_COLORS[t.name]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 12, border: 'none' }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <div className="text-2xl font-semibold text-slate-900 dark:text-white">{tierTotal}</div>
                  <div className="text-xs text-slate-500">leads</div>
                </div>
              </div>
              <ul className="mt-2 space-y-2">
                {tierData.map((t) => (
                  <li key={t.name} className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 capitalize text-slate-600 dark:text-slate-300">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: TIER_COLORS[t.name] }} />
                      {t.name}
                    </span>
                    <span className="font-medium text-slate-900 dark:text-white">{t.value}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="card xl:col-span-2">
          <h2 className="mb-4 font-semibold text-slate-900 dark:text-white">Campaign performance</h2>
          {data.campaigns.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">No campaigns yet.</p>
          ) : (
            <ul className="space-y-5">
              {data.campaigns.map((c) => (
                <li key={c.id}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <span className="font-medium text-slate-900 dark:text-white">{c.name}</span>
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${STATUS_STYLES[c.status] ?? STATUS_STYLES.draft}`}>
                        {c.status.replace('_', ' ')}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500">
                      {c.total_leads} leads &middot; {pct(c.reply_rate)} reply rate
                    </span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-white/5">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-700 transition-all duration-700"
                      style={{ width: `${c.progress}%` }}
                    />
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">{pct(c.progress)} of leads contacted</div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card">
          <div className="mb-3 flex items-center gap-2">
            <Video className="h-5 w-5 text-brand-600 dark:text-brand-300" />
            <h2 className="font-semibold text-slate-900 dark:text-white">Video engagement</h2>
          </div>
          <div className="text-3xl font-semibold text-slate-900 dark:text-white">{ve.videos}</div>
          <div className="text-sm text-slate-500">video outreach records</div>
          <p className="mt-4 rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-600 dark:bg-white/5 dark:text-slate-400">
            {ve.available
              ? `${ve.views} total views recorded.`
              : 'View counts are not available. Loom does not expose viewer analytics to this app, so engagement is shown only when you record it.'}
          </p>
        </div>
      </div>
    </div>
  )
}
