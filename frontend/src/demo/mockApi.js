// Axios adapter for the static GitHub Pages preview. Reads come from fixtures captured from the real backend
// (scripts/capture-demo-fixtures.mjs). Anything that would change data is refused with a clear message.
import { AxiosError } from 'axios'
import fx from './fixtures.json'

const NOTE = 'This is a static preview with sample data, so this action is switched off. Run the full app from the GitHub repo to use it (see the README).'

const reply = (config, data, status = 200) => {
  const response = { data, status, statusText: status < 400 ? 'OK' : 'Error', headers: {}, config, request: {} }
  if (status >= 400) return Promise.reject(new AxiosError(String(data?.detail || 'Error'), 'ERR_BAD_REQUEST', config, {}, response))
  return Promise.resolve(response)
}
const refuse = (config, detail = NOTE) => reply(config, { detail }, 403)

const paged = (items, p) => {
  const pageSize = Math.max(1, Math.min(+p.page_size || 25, 100))
  const page = Math.max(1, +p.page || 1)
  return { items: items.slice((page - 1) * pageSize, page * pageSize), total: items.length, page, page_size: pageSize }
}
const leadList = (p = {}) => {
  const q = (p.q || '').trim().toLowerCase()
  let rows = fx.leads.filter((l) =>
    (!q || [l.company_name, l.contact_name, l.email, l.industry].some((v) => (v || '').toLowerCase().includes(q))) &&
    (!p.tier || l.tier === p.tier) && (!p.status || l.status === p.status) && (!p.email_status || l.email_status === p.email_status))
  if (p.sort === 'score') rows = [...rows].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  return paged(rows, p)
}

const csv = (rows) => {
  const cols = ['company_name', 'contact_name', 'email', 'industry', 'status', 'tier', 'score']
  const esc = (v) => { const s = String(v ?? ''); return /^[=+\-@]/.test(s) ? `'${s}` : s }  // same formula-injection rule as the backend export
  return [cols.join(','), ...rows.map((r) => cols.map((c) => `"${esc(r[c]).replace(/"/g, '""')}"`).join(','))].join('\n')
}

export function mockAdapter(config) {
  const method = (config.method || 'get').toLowerCase()
  const url = (config.url || '').split('?')[0].replace(/^\/api\/v1/, '')
  const p = config.params || {}
  let m

  if (url === '/auth/config') return reply(config, { allow_registration: false, demo_mode: true, static_preview: true, demo_email: 'demo@aioutreach.pro', demo_password: 'Demo1234!' })
  if (method === 'post' && url === '/auth/login') return reply(config, { access_token: 'static-preview', refresh_token: 'static-preview', token_type: 'bearer' })
  if (method === 'post' && url === '/auth/refresh') return reply(config, { access_token: 'static-preview', refresh_token: 'static-preview', token_type: 'bearer' })
  if (method === 'post' && (m = url.match(/^\/emails\/generate$/))) {
    let body = {}
    try { body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {} } catch { /* ignore */ }
    return fx.generated[body.lead_id] ? reply(config, fx.generated[body.lead_id]) : refuse(config)
  }
  if (method !== 'get') return refuse(config)

  if (url === '/leads') return reply(config, leadList(p))
  if (url === '/inbox') return reply(config, fx.inbox.filter((i) => !p.label || i.label === p.label))
  if (url === '/videos') return reply(config, fx.videos.filter((v) => !p.lead_id || v.lead_id === +p.lead_id))
  if ((m = url.match(/^\/crm\/leads\/(\d+)$/))) return fx.crm[m[1]] ? reply(config, fx.crm[m[1]]) : reply(config, { detail: 'Not found' }, 404)
  if ((m = url.match(/^\/leads\/(\d+)\/research$/))) return reply(config, fx.research[m[1]] ?? { detail: 'No research yet' }, fx.research[m[1]] ? 200 : 404)
  if ((m = url.match(/^\/campaigns\/(\d+)\/drafts$/))) return reply(config, fx.campaignDrafts[m[1]] ?? [])
  if ((m = url.match(/^\/campaigns\/(\d+)$/))) return fx.campaign[m[1]] ? reply(config, fx.campaign[m[1]]) : reply(config, { detail: 'Not found' }, 404)
  if ((m = url.match(/^\/videos\/(\d+)\/cover\.svg$/))) return reply(config, new Blob([fx.covers[m[1]] || ''], { type: 'image/svg+xml' }))
  if (/xlsx/.test(config.url || '')) return refuse(config, 'The Excel report needs the full app. CSV export works in this preview.')
  if (/^\/(crm\/export|leads\/export)/.test(url)) return reply(config, new Blob([csv(fx.leads)], { type: 'text/csv' }))
  if (url in fx.get) return reply(config, fx.get[url])
  return reply(config, { detail: 'Not available in the static preview' }, 404)
}
