// Captures the API responses of a locally running backend (seeded demo data) into src/demo/fixtures.json.
// The static GitHub Pages preview serves these instead of a real server.
//   1) start the backend with SEED_DEMO_DATA=true on a throwaway database
//   2) node scripts/capture-demo-fixtures.mjs [http://localhost:8000]
import { writeFileSync } from 'node:fs'
const BASE = (process.argv[2] || 'http://localhost:8000') + '/api/v1'
const login = await (await fetch(BASE + '/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: 'demo@aioutreach.pro', password: 'Demo1234!' }) })).json()
const H = { Authorization: 'Bearer ' + login.access_token, 'content-type': 'application/json' }
const get = async (p, text = false) => { const r = await fetch(BASE + p, { headers: H }); if (!r.ok) throw new Error(p + ' ' + r.status); return text ? r.text() : r.json() }
const post = async (p, body) => { const r = await fetch(BASE + p, { method: 'POST', headers: H, body: JSON.stringify(body) }); if (!r.ok) throw new Error(p + ' ' + r.status); return r.json() }

const fx = { get: {}, leads: [], crm: {}, research: {}, campaign: {}, campaignDrafts: {}, inbox: [], videos: [], covers: {}, generated: {} }
for (const p of ['/auth/me', '/dashboard/summary', '/analytics/overview', '/analytics/campaigns', '/scoring/summary', '/campaigns', '/followups/due', '/settings/org', '/settings/users', '/settings/audit', '/settings/readiness', '/integrations', '/leads/capabilities', '/videos/capabilities', '/assistant/runs']) fx.get[p] = await get(p)
fx.leads = (await get('/leads?page_size=100&sort=score')).items
fx.inbox = await get('/inbox')
fx.videos = await get('/videos')
for (const l of fx.leads) {
  fx.crm[l.id] = await get(`/crm/leads/${l.id}`)
  try { fx.research[l.id] = await get(`/leads/${l.id}/research`) } catch { fx.research[l.id] = null }
  fx.generated[l.id] = await post('/emails/generate', { lead_id: l.id, tone: 'professional' })
}
for (const c of fx.get['/campaigns']) { fx.campaign[c.id] = await get(`/campaigns/${c.id}`); fx.campaignDrafts[c.id] = await get(`/campaigns/${c.id}/drafts`) }
for (const v of fx.videos) { try { fx.covers[v.id] = await get(`/videos/${v.id}/cover.svg`, true) } catch {} }
writeFileSync(new URL('../src/demo/fixtures.json', import.meta.url), JSON.stringify(fx))
console.log('leads', fx.leads.length, 'campaigns', fx.get['/campaigns'].length, 'inbox', fx.inbox.length, 'videos', fx.videos.length)
