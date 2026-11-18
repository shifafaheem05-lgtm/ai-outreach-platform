# AI Outreach Pro

AI-assisted B2B outreach platform: lead discovery, website research, lead scoring, personalized email and video scripts, follow-ups, reply classification, CRM and analytics. Human approval is required before anything is sent to a prospect.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, schema, API plan and roadmap.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Structure, database, auth/RBAC, dashboard, frontend shell | **Done** |
| 2 | Lead import, dedupe, free email check, website research, scoring | **Done** |
| 3 | AI email writer, campaigns, sending, approvals, suppression | **Done** |
| 4 | Loom video workflow and scripts | **Done** |
| 5 | Follow-ups, reply detection and classification | **Done** |
| 6 | Analytics, CRM export, assistant, hardening, tests | **Done** |

All 14 pages are live. No fake buttons: everything shown is backed by the API.

## Runs with zero paid services

- Leads: CSV import and manual entry.
- Email check: syntax + DNS lookup (confirms the domain accepts mail, not that the mailbox exists).
- AI: optional. Use a free provider (Groq, Gemini) or local Ollama via `OPENAI_*` in `.env`; without it, research reports are extractive and say so.
- Sending and reading replies: Gmail/Outlook/any SMTP+IMAP with an app password (Integrations page), subject to your provider's daily limits.
- Scheduler: runs inside the app (every 60 s); no Redis or Celery needed.

## Quick start (no Postgres or Redis needed)

```bash
cp .env.example backend/.env
# in backend/.env set:  DATABASE_URL=sqlite:///./dev.db

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000/docs

# Frontend (new terminal)
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Demo login (seeded when `SEED_DEMO_DATA=true`): `demo@aioutreach.pro` / `Demo1234!`
All demo companies and contacts are fictional (`.example` domains).

## Deployment (Docker, PostgreSQL)

```bash
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
export POSTGRES_PASSWORD=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
export PUBLIC_BASE_URL=https://outreach.example.com     # must be reachable by recipients (unsubscribe links)
docker compose up -d --build
```

- `docker compose` refuses to start if any of those four values is missing. Save them somewhere safe: losing `ENCRYPTION_KEY` makes stored mailbox passwords unreadable.
- The container runs `alembic upgrade head` on start, as a non-root user, with a health check at `/api/health`. PostgreSQL is not exposed to the host.
- With `APP_ENV=production` the app **refuses to start** on: weak `SECRET_KEY`, missing/invalid `ENCRYPTION_KEY`, `SEED_DEMO_DATA=true`, SQLite, or a localhost `PUBLIC_BASE_URL`.
- Put it behind HTTPS (Caddy, nginx, a cloud load balancer). If the proxy is not on the container's loopback, set `FORWARDED_ALLOW_IPS` to its address so login rate-limiting sees real client IPs.
- **Run exactly one app process/replica.** The e-mail scheduler lives inside it. Sends are claimed atomically so an accidental second process will not double-send, but it is not a supported scale-out setup.
- Create your first admin by registering on the login page, then set `ALLOW_REGISTRATION=false` to close sign-up; add colleagues in Settings > Team.
- Backups: `docker compose exec db pg_dump -U postgres ai_outreach_pro > backup.sql`
- Upgrades: pull, `docker compose up -d --build` (migrations run automatically).

## Configuration

Everything is configured through environment variables; see `.env.example`.
Generate an encryption key for stored credentials:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In production set `SECRET_KEY` and `ENCRYPTION_KEY` explicitly and set `SEED_DEMO_DATA=false`.

## Tests

```bash
cd backend && pip install -r requirements-dev.txt
pytest -q                                   # SQLite (default)
TEST_DATABASE_URL=postgresql+psycopg2://user:pw@localhost/empty_db pytest -q   # PostgreSQL
# browser end-to-end (server running with demo data; needs `npm i playwright`):
BASE_URL=http://localhost:8000 node scripts/e2e_smoke.mjs
```

## Compliance notes

- No prospect is contacted without an approval record (enforced from Phase 3).
- Suppression list, unsubscribe link, physical address and sending limits are enforced at send time.
- Loom has no public API to create or upload videos. The Video Studio produces scripts and a recording checklist; you record in Loom and paste the share link back.
- Website research respects robots.txt and stores source URLs; lead sources are licensed APIs and CSV import.
- Sending to EU/UK contacts requires a lawful basis. This software does not provide legal advice.


## Going live: important notes

- Security notes: sessions can be revoked (changing a password signs out every other device); mailbox hosts must be public addresses in production; see `docs/PROJECT_ANALYSIS.md` and `docs/CHANGES.md`.

- **Gmail**: turn on 2-Step Verification, create a 16-character App Password, add it on the Integrations page, then use "Test connection".
- **PUBLIC_BASE_URL** in `.env` must be a URL recipients can reach (not localhost), otherwise unsubscribe links in real emails will not work.
- **Compliance**: set your postal address and sender name in Settings; sending is blocked until you do. Opt-outs and bounces are suppressed permanently.
- **Approval flow**: campaign drafts -> submit -> manager approves -> start. One-off sends and inbox replies need explicit confirmation. The assistant never sends.
- **Production**: see **Deployment** above (the app refuses to start with unsafe settings).
- **Loom**: the app stores links and scripts; it cannot record or upload to Loom for you.
- **Email checks** confirm the domain accepts mail, not that the mailbox exists.

Single-server build: `cd frontend && npm run build`, then run uvicorn; the app serves the UI at http://localhost:8000.
