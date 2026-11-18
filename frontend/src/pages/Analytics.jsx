import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CalendarCheck, CheckCircle2, MailCheck, MailX, MessageSquareReply, Send } from 'lucide-react'
import api, { errorMessage } from '../api/client'
import StatCard from '../components/StatCard'
import { Card, Empty, Notice, Spinner, StatusPill } from '../components/ui'

const COLORS = { interested: '#10b981', meeting_requested: '#7c3aed', need_more_information: '#a78bfa', follow_up_later: '#f59e0b', not_interested: '#ef4444', out_of_office: '#94a3b8' }
const tip = { contentStyle: { borderRadius: 12, border: 'none', boxShadow: '0 8px 24px rgba(0,0,0,.15)' } }
const axis = { tick: { fontSize: 11, fill: '#94a3b8' }, tickLine: false, axisLine: false }
const short = (d) => new Date(d + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

export default function Analytics() {
  const ov = useQuery({ queryKey: ['analytics'], queryFn: async () => (await api.get('/analytics/overview')).data })
  const camps = useQuery({ queryKey: ['analytics-campaigns'], queryFn: async () => (await api.get('/analytics/campaigns')).data })
  if (ov.isLoading || camps.isLoading) return <Spinner className="h-6 w-6" />
  if (ov.error) return <Notice kind="error">{errorMessage(ov.error)}</Notice>
  const d = ov.data
  const labels = Object.entries(d.replies_by_label).map(([name, value]) => ({ name, value }))
  const cs = camps.data ?? []
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Emails sent" value={d.emails_sent} icon={Send} hint={`${d.total_leads} leads · ${d.qualified_leads} qualified`} />
        <StatCard label="Not bounced" value={`${d.delivery_rate}%`} icon={MailCheck} hint="Accepted and not returned" />
        <StatCard label="Bounce rate" value={`${d.bounce_rate}%`} icon={MailX} />
        <StatCard label="Reply rate" value={`${d.reply_rate}%`} icon={MessageSquareReply} />
        <StatCard label="Positive responses" value={`${d.positive_response_rate}%`} icon={CheckCircle2} hint="Interested, meeting, more info" />
        <StatCard label="Meetings requested" value={d.meetings_generated} icon={CalendarCheck} />
        <StatCard label="Videos" value={d.video_engagement.videos} hint={d.video_engagement.available ? `${d.video_engagement.views} views you entered` : 'No view counts entered'} />
      </div>
      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Emails and replies, last 14 days" className="xl:col-span-2">
          <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={d.activity} margin={{ left: -20, right: 8, top: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.2} vertical={false} /><XAxis dataKey="date" tickFormatter={short} {...axis} /><YAxis allowDecimals={false} {...axis} /><Tooltip labelFormatter={short} {...tip} />
            <Line type="monotone" dataKey="sent" name="Sent" stroke="#7c3aed" strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="replies" name="Replies" stroke="#10b981" strokeWidth={2.5} dot={false} />
          </LineChart></ResponsiveContainer></div>
        </Card>
        <Card title="Reply types">
          {labels.length === 0 ? <Empty>No classified replies yet.</Empty> : (<>
            <div className="h-44"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={labels} dataKey="value" innerRadius={45} outerRadius={70} paddingAngle={2} stroke="none">{labels.map((l) => <Cell key={l.name} fill={COLORS[l.name]} />)}</Pie><Tooltip {...tip} /></PieChart></ResponsiveContainer></div>
            <ul className="mt-2 space-y-1">{labels.map((l) => <li key={l.name} className="flex items-center justify-between text-xs"><span className="flex items-center gap-2 capitalize"><span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[l.name] }} />{l.name.replace(/_/g, ' ')}</span><b>{l.value}</b></li>)}</ul></>)}
        </Card>
      </div>
      <Card title="Campaign performance">
        {cs.length === 0 ? <Empty>No campaigns yet.</Empty> : (<>
          <div className="mb-4 h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={cs} margin={{ left: -20, right: 8 }}><CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.2} vertical={false} /><XAxis dataKey="name" {...axis} /><YAxis unit="%" {...axis} /><Tooltip {...tip} /><Bar dataKey="reply_rate" name="Reply rate %" fill="#7c3aed" radius={[6, 6, 0, 0]} /><Bar dataKey="bounce_rate" name="Bounce rate %" fill="#f59e0b" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
          <div className="-mx-5 overflow-x-auto"><table className="w-full min-w-[640px] text-left text-sm">
            <thead><tr className="border-b border-slate-200/70 text-xs uppercase text-slate-500 dark:border-white/5">{['Campaign', 'Status', 'Leads', 'Sent', 'Bounced', 'Replied', 'Reply rate', 'Positive', 'Meetings'].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>{cs.map((c) => <tr key={c.id} className="border-b border-slate-100 last:border-0 dark:border-white/5"><td className="px-4 py-2.5 font-medium">{c.name}</td><td className="px-4 py-2.5"><StatusPill status={c.status} /></td>{[c.leads, c.sent, c.bounced, c.replied, `${c.reply_rate}%`, c.positive, c.meetings].map((v, i) => <td key={i} className="px-4 py-2.5">{v}</td>)}</tr>)}</tbody></table></div></>)}
      </Card>
      <div className="space-y-2">{d.notes.map((n) => <Notice key={n}>{n}</Notice>)}</div>
    </div>
  )
}
