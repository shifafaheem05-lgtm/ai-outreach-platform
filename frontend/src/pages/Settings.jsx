import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Circle } from 'lucide-react'
import api, { tokenStore } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Card, ErrorNotice, Notice, Spinner, fmtDate } from '../components/ui'

function OrgForm({ manager }) {
  const qc = useQueryClient()
  const org = useQuery({ queryKey: ['org'], queryFn: async () => (await api.get('/settings/org')).data })
  const [f, setF] = useState(null)
  useEffect(() => { if (org.data) setF(org.data) }, [org.data])
  const save = useMutation({
    mutationFn: async () => (await api.patch('/settings/org', { name: f.name, physical_address: f.physical_address, sender_name: f.sender_name, daily_send_limit: +f.daily_send_limit, hourly_send_limit: +f.hourly_send_limit })).data,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['org'] }); qc.invalidateQueries({ queryKey: ['readiness'] }) },
  })
  if (!f) return <Card><Spinner /></Card>
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <Card title="Organization and sending">
      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <div><label className="label" htmlFor="o-n">Organization name</label><input id="o-n" className="input" value={f.name} onChange={set('name')} disabled={!manager} /></div>
        <div><label className="label" htmlFor="o-s">Sender name (shown in From)</label><input id="o-s" className="input" value={f.sender_name} onChange={set('sender_name')} disabled={!manager} /></div>
        <div className="sm:col-span-2"><label className="label" htmlFor="o-a">Postal address (added to every email)</label><input id="o-a" className="input" value={f.physical_address} onChange={set('physical_address')} disabled={!manager} placeholder="Street, city, country" /></div>
        <div><label className="label" htmlFor="o-d">Daily send limit (max 500)</label><input id="o-d" type="number" min="1" max="500" className="input" value={f.daily_send_limit} onChange={set('daily_send_limit')} disabled={!manager} /></div>
        <div><label className="label" htmlFor="o-h">Hourly send limit (max 100)</label><input id="o-h" type="number" min="1" max="100" className="input" value={f.hourly_send_limit} onChange={set('hourly_send_limit')} disabled={!manager} /></div>
        <div className="sm:col-span-2 flex items-center gap-3">{manager && <button className="btn-primary" disabled={save.isPending}>Save</button>}{save.isSuccess && <span className="text-sm text-emerald-600">Saved</span>}</div>
        <div className="sm:col-span-2"><ErrorNotice error={save.error} /></div>
      </form>
    </Card>
  )
}

function Team() {
  const qc = useQueryClient()
  const { user } = useAuth()
  const admin = user.role === 'admin'
  const users = useQuery({ queryKey: ['users'], queryFn: async () => (await api.get('/settings/users')).data })
  const [n, setN] = useState({ name: '', email: '', password: '', role: 'member' })
  const refresh = () => qc.invalidateQueries({ queryKey: ['users'] })
  const patch = useMutation({ mutationFn: async ({ id, ...b }) => api.patch(`/settings/users/${id}`, b), onSuccess: refresh })
  const add = useMutation({ mutationFn: async () => api.post('/settings/users', n), onSuccess: () => { setN({ name: '', email: '', password: '', role: 'member' }); refresh() } })
  return (
    <Card title="Team and roles">
      <p className="mb-3 text-xs text-slate-500">Members write and research. Managers also approve and start campaigns and manage mailboxes. Admins manage the team.</p>
      <ul className="divide-y divide-slate-100 dark:divide-white/5">{(users.data ?? []).map((u) => (
        <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
          <div><div className="font-medium">{u.name}{!u.is_active && <span className="ml-2 text-xs text-red-600">disabled</span>}</div><div className="text-xs text-slate-500">{u.email}</div></div>
          {admin ? <div className="flex items-center gap-2"><select className="input !w-auto !py-1.5" value={u.role} onChange={(e) => patch.mutate({ id: u.id, role: e.target.value })} aria-label={`Role for ${u.name}`}>{['member', 'manager', 'admin'].map((r) => <option key={r}>{r}</option>)}</select>
            <button className="btn-secondary !py-1.5" onClick={() => patch.mutate({ id: u.id, is_active: !u.is_active })}>{u.is_active ? 'Disable' : 'Enable'}</button></div> : <span className="text-xs capitalize">{u.role}</span>}
        </li>))}</ul>
      <ErrorNotice error={patch.error} />
      {admin && <form className="mt-4 grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
        <input className="input" placeholder="Name" required value={n.name} onChange={(e) => setN({ ...n, name: e.target.value })} aria-label="New user name" />
        <input className="input" type="email" placeholder="Email" required value={n.email} onChange={(e) => setN({ ...n, email: e.target.value })} aria-label="New user email" />
        <input className="input" type="password" placeholder="Temporary password (8+)" minLength={8} required value={n.password} onChange={(e) => setN({ ...n, password: e.target.value })} aria-label="New user password" autoComplete="new-password" />
        <select className="input" value={n.role} onChange={(e) => setN({ ...n, role: e.target.value })} aria-label="New user role">{['member', 'manager', 'admin'].map((r) => <option key={r}>{r}</option>)}</select>
        <div className="sm:col-span-2"><button className="btn-primary" disabled={add.isPending}>Add team member</button></div><div className="sm:col-span-2"><ErrorNotice error={add.error} /></div>
      </form>}
    </Card>
  )
}

function Account() {
  const { user } = useAuth()
  const [f, setF] = useState({ current_password: '', new_password: '', confirm: '' })
  const [mismatch, setMismatch] = useState(false)
  const change = useMutation({
    mutationFn: async () => (await api.post('/auth/change-password', { current_password: f.current_password, new_password: f.new_password })).data,
    onSuccess: (tokens) => { tokenStore.set(tokens); setF({ current_password: '', new_password: '', confirm: '' }) },
  })
  const submit = (e) => {
    e.preventDefault()
    const bad = f.new_password !== f.confirm
    setMismatch(bad)
    if (!bad) change.mutate()
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <Card title="Your account">
      <p className="mb-3 text-xs text-slate-500">Signed in as {user.name} ({user.email}). Changing your password signs you out of all other devices.</p>
      <form className="grid gap-3 sm:grid-cols-3" onSubmit={submit}>
        <div><label className="label" htmlFor="pw-c">Current password</label><input id="pw-c" className="input" type="password" required autoComplete="current-password" value={f.current_password} onChange={set('current_password')} /></div>
        <div><label className="label" htmlFor="pw-n">New password</label><input id="pw-n" className="input" type="password" required minLength={8} autoComplete="new-password" value={f.new_password} onChange={set('new_password')} /></div>
        <div><label className="label" htmlFor="pw-r">Repeat new password</label><input id="pw-r" className="input" type="password" required minLength={8} autoComplete="new-password" value={f.confirm} onChange={set('confirm')} /></div>
        <div className="sm:col-span-3 flex items-center gap-3"><button className="btn-primary" disabled={change.isPending}>Change password</button>{change.isSuccess && <span className="text-sm text-emerald-600">Password changed</span>}</div>
        <div className="sm:col-span-3 space-y-2">{mismatch && <Notice kind="error">The two new passwords do not match.</Notice>}<p className="text-xs text-slate-500">At least 8 characters with a letter and a number.</p><ErrorNotice error={change.error} /></div>
      </form>
    </Card>
  )
}

function Audit() {
  const log = useQuery({ queryKey: ['audit'], queryFn: async () => (await api.get('/settings/audit')).data })
  return (
    <Card title="Audit log (latest 100)">
      <div className="max-h-72 overflow-y-auto"><table className="w-full text-left text-xs"><tbody>{(log.data ?? []).map((a) => <tr key={a.id} className="border-b border-slate-100 dark:border-white/5"><td className="py-1.5 pr-3 text-slate-500">{fmtDate(a.at)}</td><td className="py-1.5 pr-3 font-medium">{a.action}</td><td className="py-1.5 text-slate-500">{a.entity} {a.entity_id ?? ''}</td></tr>)}</tbody></table></div>
    </Card>
  )
}

export default function Settings() {
  const { user } = useAuth()
  const manager = ['manager', 'admin'].includes(user.role)
  const ready = useQuery({ queryKey: ['readiness'], queryFn: async () => (await api.get('/settings/readiness')).data })
  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <div className="space-y-6 xl:col-span-2">
        <OrgForm manager={manager} />
        <Account />
        {manager && <Team />}
        {user.role === 'admin' && <Audit />}
      </div>
      <div className="space-y-4">
        <Card title="Ready to send?">
          <ul className="space-y-2 text-sm">{(ready.data?.checks ?? []).map((c) => <li key={c.id} className="flex items-center gap-2">{c.ok ? <Check className="h-4 w-4 text-emerald-600" /> : <Circle className="h-4 w-4 text-slate-300" />}<span className={c.ok ? '' : 'text-slate-500'}>{c.label}</span></li>)}</ul>
        </Card>
        <Notice>Compliance basics are built in: every email carries your postal address and a one-click unsubscribe link, opted-out and bounced addresses are never emailed again, and sending is rate-limited. Rules differ by country (for example GDPR/PECR for EU and UK recipients), so check what applies to you. This is not legal advice.</Notice>
      </div>
    </div>
  )
}
