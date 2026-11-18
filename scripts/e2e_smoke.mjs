// Browser end-to-end smoke test against a RUNNING server (backend + built UI).
// Usage: BASE_URL=http://localhost:8000 node scripts/e2e_smoke.mjs   (needs `playwright` + a Chromium install)
// Requires the demo data (SEED_DEMO_DATA=true) and a non-production APP_ENV.
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:8000'
const ROUTES = ['/', '/lead-discovery', '/lead-research', '/lead-scoring', '/campaigns', '/email-writer', '/video-studio', '/follow-ups', '/inbox', '/crm', '/analytics', '/integrations', '/settings', '/assistant']
const results = []
const ok = (name, pass, detail = '') => { results.push({ name, pass, detail }); console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -> ' + detail : ''}`) }

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true })
const page = await ctx.newPage()
const problems = []
page.on('pageerror', (e) => problems.push('pageerror: ' + e.message))
page.on('console', (m) => m.type() === 'error' && problems.push('console: ' + m.text()))
page.on('response', (r) => { if (r.url().includes('/api/') && r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`) })

// ---- 1. login page + demo login
await page.goto(BASE + '/login')
ok('login page shows "Create a workspace" when registration is open', await page.getByRole('button', { name: 'Create a workspace' }).isVisible())
await page.fill('input[type=email]', 'demo@aioutreach.pro')
await page.fill('input[type=password]', 'Demo1234!')
await page.getByRole('button', { name: 'Sign in' }).click()
await page.waitForURL(BASE + '/')
await page.getByRole('heading', { name: 'Dashboard' }).waitFor()  // pages are lazy-loaded: wait for mount
ok('demo login reaches dashboard', await page.getByRole('button', { name: 'Sign out' }).isVisible())

// ---- 2. every page renders without JS errors or failed API calls
for (const r of ROUTES) {
  const before = problems.length
  await page.goto(BASE + r)
  await page.waitForLoadState('networkidle')
  const body = (await page.locator('body').innerText()).trim()
  const boundary = await page.getByText('Something went wrong on this page').count()
  ok(`page ${r} renders cleanly`, body.length > 50 && boundary === 0 && problems.length === before, problems.slice(before).join(' | '))
}

// ---- 3. CRM: export + delete lead
await page.goto(BASE + '/crm')
await page.waitForLoadState('networkidle')
const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'CSV' }).click()])
ok('CRM CSV export downloads', dl.suggestedFilename() === 'leads.csv')
const token = await page.evaluate(() => localStorage.getItem('aop_access'))
const mk = await page.request.post(BASE + '/api/v1/leads', { headers: { Authorization: 'Bearer ' + token }, data: { company_name: 'E2E Delete Me Ltd', email: 'e2e@delete-me-e2e.com', website: 'delete-me-e2e.com' } })
ok('API creates a lead', mk.status() === 201)
await page.reload()
await page.waitForLoadState('networkidle')
await page.getByPlaceholder(/search/i).first().fill('E2E Delete Me')
await page.getByText('E2E Delete Me Ltd').first().click()
page.once('dialog', (d) => d.accept())
await page.getByRole('button', { name: /Delete lead/ }).click()
await page.waitForTimeout(800)
const gone = await page.request.get(BASE + '/api/v1/leads?q=E2E%20Delete', { headers: { Authorization: 'Bearer ' + token } })
ok('deleting a lead from the UI removes it', (await gone.json()).total === 0)
ok('profile panel closes after delete', await page.getByText('Select a lead to see their profile').isVisible())

// ---- 4. register a fresh workspace, change password, other sessions revoked
await page.getByRole('button', { name: 'Sign out' }).click()
await page.goto(BASE + '/login')
await page.getByRole('button', { name: 'Create a workspace' }).click()
const email = `e2e${Date.now()}@e2e-test.com`
await page.getByLabel(/name/i).first().fill('E2E User').catch(() => {})
const inputs = page.locator('form input')
const count = await inputs.count()
// fill by order: whatever the form shows (name, org, email, password)
for (let i = 0; i < count; i++) {
  const t = await inputs.nth(i).getAttribute('type')
  const ph = ((await inputs.nth(i).getAttribute('placeholder')) || '') + ((await inputs.nth(i).getAttribute('autocomplete')) || '')
  if (t === 'email') await inputs.nth(i).fill(email)
  else if (t === 'password') await inputs.nth(i).fill('Password123')
  else if (/org|company|workspace/i.test(ph + (await inputs.nth(i).getAttribute('id')))) await inputs.nth(i).fill('E2E Org')
  else await inputs.nth(i).fill('E2E User')
}
await page.getByRole('button', { name: 'Create account' }).click()
await page.waitForURL(BASE + '/')
const oldRefresh = await page.evaluate(() => localStorage.getItem('aop_refresh'))
await page.goto(BASE + '/settings')
await page.getByLabel('Current password').fill('Password123')
await page.getByLabel('New password', { exact: true }).fill('NewPassword456')
await page.getByLabel('Repeat new password').fill('Different789')
await page.getByRole('button', { name: 'Change password' }).click()
ok('mismatched new passwords are rejected client-side', await page.getByText('do not match').isVisible())
await page.getByLabel('Repeat new password').fill('NewPassword456')
await page.getByRole('button', { name: 'Change password' }).click()
await page.getByText('Password changed').waitFor()
ok('password change succeeds and session stays signed in', true)
const stale = await page.request.post(BASE + '/api/v1/auth/refresh', { data: { refresh_token: oldRefresh } })
ok('old refresh token is revoked after password change', stale.status() === 401)
await page.getByRole('button', { name: 'Sign out' }).click()
await page.goto(BASE + '/login')
await page.fill('input[type=email]', email)
await page.fill('input[type=password]', 'NewPassword456')
await page.getByRole('button', { name: 'Sign in' }).click()
await page.waitForURL(BASE + '/')
ok('login works with the new password', true)

// ---- 5. responsive: no horizontal overflow on a phone
const phone = await browser.newContext({ viewport: { width: 375, height: 800 } })
const pp = await phone.newPage()
await pp.goto(BASE + '/login')
await pp.fill('input[type=email]', 'demo@aioutreach.pro')
await pp.fill('input[type=password]', 'Demo1234!')
await pp.getByRole('button', { name: 'Sign in' }).click()
await pp.waitForURL(BASE + '/')
for (const r of ['/', '/crm', '/campaigns', '/analytics', '/settings', '/inbox']) {
  await pp.goto(BASE + r)
  await pp.waitForLoadState('networkidle')
  const over = await pp.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  ok(`mobile 375px ${r}: no horizontal overflow`, over <= 1, `overflow ${over}px`)
}
if (process.env.SHOT_DIR) { await pp.goto(BASE + '/settings'); await pp.waitForLoadState('networkidle'); await pp.waitForTimeout(1500); await pp.screenshot({ path: process.env.SHOT_DIR + '/mobile-settings.png', fullPage: true }); await page.goto(BASE + '/settings'); await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500); await page.screenshot({ path: process.env.SHOT_DIR + '/desktop-settings.png' }) }

await browser.close()
const failed = results.filter((r) => !r.pass)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
process.exit(failed.length ? 1 : 0)
