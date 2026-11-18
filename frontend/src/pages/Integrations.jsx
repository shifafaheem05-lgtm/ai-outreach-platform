import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Mail, Plug, Trash2 } from 'lucide-react'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Card, Empty, ErrorNotice, Notice, Spinner } from '../components/ui'

const EMPTY = { label: '', preset: 'gmail', username: '', password: '', from_email: '', smtp_host: '', smtp_port: 465, security: 'ssl', imap_host: '', imap_port: 993 }

function Row({ i, manager }) {
  const qc = useQueryClient()
  const [out, setOut] = useState(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['integrations'] })
  const test = useMutation({ mutationFn: async () => (await api.post(`/integrations/${i.id}/test`)).data, onSuccess: (r) => { setOut(r); refresh() } })
  const sendTest = useMutation({ mutationFn: async () => (await api.post(`/integrations/${i.id}/send-test`)).data, onSuccess: (r) => setOut({ info: `Test email sent to ${r.sent_to}.` }) })
  const del = useMutation({ mutationFn: async () => api.delete(`/integrations/${i.id}`), onSuccess: refresh })
  const color = i.status === 'connected' ? 'text-emerald-600' : i.status === 'error' ? 'text-red-600' : 'text-amber-600'
  return (
    <li className="rounded-xl border border-slate-200 p-4 dark:border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3"><Mail className="h-5 w-5 text-brand-600" /><div><div className="font-medium">{i.label}</div><div className="text-xs text-slate-500">{i.from_email} · {i.smtp_host}{i.capabilities.receive ? ' · reading replies on' : i.imap_host ? '' : ' · no IMAP (cannot read replies)'}</div></div></div>
        <span className={`text-xs font-medium capitalize ${color}`}>{i.status}</span>
      </div>
      {manager && <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-secondary" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? <Spinner /> : null} Test connection</button>
        <button className="btn-secondary" disabled={sendTest.isPending} onClick={() => sendTest.mutate()}>Send test email to me</button>
        <button className="btn-danger" onClick={() => window.confirm('Remove this mailbox?') && del.mutate()}><Trash2 className="h-4 w-4" /> Remove</button>
      </div>}
      <div className="mt-2 space-y-2"><ErrorNotice error={test.error ?? sendTest.error ?? del.error} />
        {out?.smtp && <Notice kind={out.smtp === 'ok' ? 'ok' : 'error'}>Sending (SMTP): {out.smtp}{out.imap ? ` · Reading replies (IMAP): ${out.imap}` : ''}</Notice>}
        {out?.info && <Notice kind="ok">{out.info}</Notice>}</div>
    </li>
  )
}

export default function Integrations() {
  const qc = useQueryClient()
  const { user } = useAuth()
  const manager = ['manager', 'admin'].includes(user.role)
  const [form, setForm] = useState(EMPTY)
  const list = useQuery({ queryKey: ['integrations'], queryFn: async () => (await api.get('/integrations')).data })
  const caps = useQuery({ queryKey: ['lead-caps'], queryFn: async () => (await api.get('/leads/capabilities')).data })
  const add = useMutation({ mutationFn: async () => (await api.post('/integrations', { ...form, smtp_port: +form.smtp_port, imap_port: +form.imap_port })).data, onSuccess: () => { setForm(EMPTY); qc.invalidateQueries({ queryKey: ['integrations'] }); qc.invalidateQueries({ queryKey: ['readiness'] }) } })
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  return (
    <div className="grid gap-6 xl:grid-cols-5">
      <div className="space-y-4 xl:col-span-3">
        <Card title="Mailboxes">{list.isLoading ? <Spinner /> : list.data.length === 0 ? <Empty>No mailbox yet. Add one on the right.</Empty> : <ul className="space-y-3">{list.data.map((i) => <Row key={i.id} i={i} manager={manager} />)}</ul>}</Card>
        <Card title="AI model (optional)">
          <p className="flex items-center gap-2 text-sm"><Plug className="h-4 w-4 text-brand-600" />{caps.data?.llm.configured ? `Connected: ${caps.data.llm.model}` : 'Not configured. The app works without it using templates and rules.'}</p>
          <p className="mt-2 text-xs text-slate-500">Set <code>OPENAI_API_KEY</code>, <code>OPENAI_BASE_URL</code> and <code>OPENAI_MODEL</code> in <code>.env</code> and restart. Free options: Groq, Google Gemini, or Ollama on your own computer. Keys stay on the server and are never shown here.</p>
        </Card>
      </div>
      <div className="xl:col-span-2">
        {manager ? (
          <Card title="Add a mailbox">
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
              <div><label className="label" htmlFor="i-l">Label</label><input id="i-l" className="input" required value={form.label} onChange={set('label')} placeholder="My Gmail" /></div>
              <div><label className="label" htmlFor="i-p">Provider</label><select id="i-p" className="input" value={form.preset} onChange={set('preset')}><option value="gmail">Gmail</option><option value="outlook">Outlook / Microsoft 365</option><option value="custom">Other (custom SMTP)</option></select></div>
              <div><label className="label" htmlFor="i-u">Email / username</label><input id="i-u" className="input" required value={form.username} onChange={set('username')} autoComplete="off" /></div>
              <div><label className="label" htmlFor="i-pw">{form.preset === 'gmail' ? 'App password' : 'Password'}</label><input id="i-pw" type="password" className="input" required value={form.password} onChange={set('password')} autoComplete="new-password" /></div>
              {form.preset === 'gmail' && <Notice>Gmail needs a 16-character App Password, not your normal password. In your Google Account turn on 2-Step Verification, then create an App Password. Gmail limits sending (a few hundred a day for personal accounts), so keep your limits low.</Notice>}
              {form.preset === 'custom' && <>
                <div className="grid grid-cols-3 gap-2"><div className="col-span-2"><label className="label" htmlFor="i-h">SMTP host</label><input id="i-h" className="input" required value={form.smtp_host} onChange={set('smtp_host')} /></div><div><label className="label" htmlFor="i-sp">Port</label><input id="i-sp" type="number" className="input" value={form.smtp_port} onChange={set('smtp_port')} /></div></div>
                <div><label className="label" htmlFor="i-sec">Security</label><select id="i-sec" className="input" value={form.security} onChange={set('security')}><option value="ssl">SSL (465)</option><option value="starttls">STARTTLS (587)</option><option value="none">None</option></select></div>
                <div className="grid grid-cols-3 gap-2"><div className="col-span-2"><label className="label" htmlFor="i-ih">IMAP host (to read replies)</label><input id="i-ih" className="input" value={form.imap_host} onChange={set('imap_host')} /></div><div><label className="label" htmlFor="i-ip">Port</label><input id="i-ip" type="number" className="input" value={form.imap_port} onChange={set('imap_port')} /></div></div>
                <div><label className="label" htmlFor="i-f">From address (if different)</label><input id="i-f" className="input" value={form.from_email} onChange={set('from_email')} /></div></>}
              <ErrorNotice error={add.error} />
              <button className="btn-primary w-full" disabled={add.isPending}>{add.isPending ? <Spinner /> : null} Save mailbox</button>
              <p className="text-xs text-slate-500">Credentials are encrypted before they are stored.</p>
            </form>
          </Card>
        ) : <Notice>Ask a manager or admin to add or change mailboxes.</Notice>}
      </div>
    </div>
  )
}
