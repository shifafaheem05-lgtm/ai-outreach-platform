# AI Outreach Pro — Architecture & Roadmap

## 1. Guiding principles

- **Real functionality only.** Every button maps to a working endpoint. Where an external API does not exist (e.g. Loom has no public video-upload API), the UI says so and offers a guided manual workflow.
- **Human approval gate.** No external communication (email, reply) is sent without an explicit approval record. Initial campaigns always require approval.
- **Compliance by design.** Suppression list checked on every send, unsubscribe link and physical address injected into every email, daily/hourly sending limits, stop-on-reply, opt-out handling.
- **No invented data.** Research reports are generated only from fetched page content; every claim stores its source URL. If a fetch fails, the report says "insufficient data".
- **Respectful collection.** Website fetching honours robots.txt and a per-domain rate limit. Lead discovery uses licensed/official APIs (Apollo, Hunter, Google Places) and CSV import, not scraping that violates terms.

## 2. Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI, Pydantic v2, Uvicorn |
| ORM / DB | SQLAlchemy 2.0, PostgreSQL (SQLite for local dev/tests), Alembic |
| Background jobs | Celery + Redis (APScheduler for the periodic scheduler tick) |
| LLM | OpenAI-compatible client (configurable base URL/model) |
| ML | scikit-learn (lead scoring, reply classification fallback), LLM for zero-shot classification |
| Email | SMTP (smtplib/aiosmtplib), Gmail API (OAuth), IMAP for reply detection |
| Auth | JWT (access + refresh), bcrypt, RBAC (admin / manager / member) |
| Secrets | Fernet encryption for stored API keys and SMTP passwords |
| Frontend | React 18, Vite, Tailwind CSS, React Router, TanStack Query, Recharts |

## 3. Folder structure

```
ai-outreach-pro/
├── README.md
├── ARCHITECTURE.md
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   ├── app/
│   │   ├── main.py                  # FastAPI app factory, CORS, routers
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic settings from env
│   │   │   ├── security.py          # JWT, password hashing, Fernet
│   │   │   ├── logging.py
│   │   │   └── deps.py              # get_db, get_current_user, require_role
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   └── seed.py              # demo data
│   │   ├── models/                  # SQLAlchemy models (one file per domain)
│   │   ├── schemas/                 # Pydantic schemas
│   │   ├── api/v1/
│   │   │   ├── auth.py  users.py  dashboard.py
│   │   │   ├── leads.py  research.py  scoring.py
│   │   │   ├── campaigns.py  emails.py  approvals.py
│   │   │   ├── videos.py  followups.py  inbox.py
│   │   │   ├── crm.py  analytics.py  integrations.py
│   │   │   ├── assistant.py  settings.py  unsubscribe.py
│   │   ├── services/
│   │   │   ├── llm.py               # LLM client wrapper
│   │   │   ├── lead_sources/        # csv, apollo, hunter, places adapters
│   │   │   ├── verification.py      # email verification adapter + syntax/MX check
│   │   │   ├── research.py          # polite fetcher + LLM report
│   │   │   ├── scoring.py           # ML + rules lead scoring
│   │   │   ├── email_writer.py
│   │   │   ├── sending.py           # SMTP/Gmail senders, limits, compliance
│   │   │   ├── reply_classifier.py
│   │   │   ├── followups.py
│   │   │   ├── loom.py              # capability-aware Loom integration
│   │   │   ├── video_scripts.py
│   │   │   ├── analytics.py
│   │   │   └── assistant.py         # tool-calling agent
│   │   ├── workers/                 # Celery tasks + scheduler
│   │   └── ml/                      # training scripts, model artifacts
│   └── tests/
└── frontend/
    ├── package.json  vite.config.js  tailwind.config.js
    └── src/
        ├── api/            # axios client + hooks
        ├── components/     # Sidebar, Topbar, DataTable, StatCard, Charts, Modal
        ├── pages/          # 13 pages
        ├── context/        # AuthContext
        └── App.jsx  main.jsx  index.css
```

## 4. Database design

**users** (id, email, name, password_hash, role, org_id, is_active, created_at)
**organizations** (id, name, physical_address, sender_name, daily_send_limit, hourly_send_limit)
**integrations** (id, org_id, provider, encrypted_credentials, status, capabilities_json)
**leads** (id, org_id, company_name, website, industry, location, company_size, niche, contact_name, contact_title, email, email_status, source, source_url, score, tier, status, category, tags[], dedupe_key, created_at) — unique(org_id, dedupe_key)
**research_reports** (id, lead_id, summary, products_services, pain_points, opportunities, sources_json, model, created_at)
**lead_score_events** (id, lead_id, score, tier, features_json, model_version, created_at)
**campaigns** (id, org_id, name, tone, status[draft|pending_approval|approved|running|paused|completed], sender_integration_id, schedule_json, followup_intervals[], max_followups, created_by)
**campaign_leads** (id, campaign_id, lead_id, state, current_step, next_send_at)
**email_templates / email_drafts** (id, campaign_lead_id, step, variant[short|medium|detailed], subject, body, status[draft|approved|sent], approved_by, approved_at)
**messages** (id, lead_id, campaign_id, direction[out|in], subject, body, provider_message_id, thread_id, status[queued|sent|delivered|bounced|failed|received], sent_at, opened_at, clicked_at)
**reply_classifications** (id, message_id, label, confidence, suggested_response, reviewed)
**approvals** (id, org_id, entity_type, entity_id, requested_by, approved_by, status, decided_at)
**suppression_list** (id, org_id, email, reason[unsubscribed|bounced|complaint|manual], created_at)
**videos** (id, lead_id, campaign_id, script, intro, thumbnail_url, description, loom_url, source[loom_manual|loom_api|upload], status[script_ready|awaiting_recording|published], views, created_at)
**notes** (id, lead_id, user_id, body, created_at)
**activity_log / audit_log** (id, org_id, user_id, action, entity, entity_id, meta_json, created_at)
**assistant_runs** (id, user_id, command, plan_json, status, pending_approval, result_json)

## 5. API plan (`/api/v1`)

| Area | Endpoints |
|---|---|
| Auth | POST /auth/register, /auth/login, /auth/refresh, GET /auth/me |
| Dashboard | GET /dashboard/summary |
| Leads | GET/POST /leads, POST /leads/import-csv, POST /leads/discover, POST /leads/verify, POST /leads/dedupe, PATCH/DELETE /leads/{id} |
| Research | POST /leads/{id}/research, GET /leads/{id}/research |
| Scoring | POST /scoring/run, GET /scoring/summary, POST /scoring/train |
| Campaigns | CRUD /campaigns, POST /campaigns/{id}/leads, /submit-approval, /start, /pause |
| Email writer | POST /emails/generate, POST /emails/followups, PATCH /emails/drafts/{id} |
| Approvals | GET /approvals, POST /approvals/{id}/approve, /reject |
| Videos | POST /videos/script, GET /videos, PATCH /videos/{id}/link, GET /videos/capabilities |
| Follow-ups | GET /followups/due, POST /followups/generate |
| Inbox | GET /inbox, POST /inbox/sync, POST /inbox/{id}/classify, POST /inbox/{id}/reply (approval-gated) |
| CRM | GET /crm/leads/{id}, notes, tags, status, GET /crm/export?format=csv|xlsx |
| Analytics | GET /analytics/overview, /analytics/campaigns |
| Integrations | GET/POST /integrations, DELETE /integrations/{id}, POST /integrations/{id}/test |
| Assistant | POST /assistant/command, POST /assistant/runs/{id}/approve |
| Public | GET /unsubscribe/{token} |

## 6. Compliance & safety controls

1. Suppression list enforced at send time (not just at queue time).
2. Every outbound email includes unsubscribe link, one-click `List-Unsubscribe` header, and the organization's physical address (CAN-SPAM); settings block sending until these are configured.
3. Daily/hourly caps and randomized send spacing per mailbox.
4. Approval required: initial campaign launch, any AI-suggested reply, assistant-initiated sends.
5. Follow-ups auto-stop on reply, bounce, or opt-out.
6. Research fetcher: robots.txt check, identifiable User-Agent, rate-limited; stores source URLs.
7. AI voiceover disabled by default; enabling requires a recorded authorization/disclosure acknowledgement.
8. Credentials encrypted at rest; audit log for sensitive actions.
9. GDPR/PECR note: EU/UK recipients require a documented lawful basis; the lead record stores `source` and a region flag, and the UI warns on EU/UK contacts.

## 7. Loom integration reality

Loom does not offer a public API for creating or uploading videos. Supported:
- **Script + checklist** generation for the user to record via Loom's app/extension.
- **Paste-back flow:** user pastes the resulting Loom share link; the app validates it, stores it, and inserts it (with a thumbnail/description) into emails.
- **Embeds/analytics:** only where Loom exposes them; otherwise views are marked "not available" in the UI.

The `/videos/capabilities` endpoint reports exactly what is available so the UI never implies automation that does not exist.

## 8. Lead scoring model

Features: industry match, company-size fit, title seniority, email verification status, research-derived fit (LLM 0–1), engagement (opens/clicks/replies). Cold start: weighted rules. Once ≥200 labeled outcomes exist, a gradient-boosted classifier (scikit-learn) is trained and replaces rules. Tiers: Hot ≥ 70, Warm 40–69, Cold < 40.

## 9. Roadmap

| Phase | Scope |
|---|---|
| 1 | Project structure, DB, auth/RBAC, dashboard, frontend shell with all pages, demo data |
| 2 | Lead import/discovery, dedupe, verification, website research, scoring |
| 3 | AI email writer, campaigns, SMTP/Gmail sending, approvals, suppression, limits |
| 4 | Loom video studio: scripts, thumbnails/descriptions, link storage, email linking |
| 5 | Follow-ups, IMAP reply detection, reply classification, suggested responses |
| 6 | Analytics, CRM exports, AI assistant, security hardening, full test suite |


## Implementation notes (deviations from the plan)

- Background jobs use an in-process APScheduler tick (60 s) instead of Celery + Redis, so the app runs with no extra services.
- Mailboxes connect via SMTP/IMAP app passwords instead of Gmail OAuth (free, no Google review needed).
- Reply classification, lead scoring and the assistant are rule-based, with an optional LLM (any OpenAI-compatible endpoint) for writing and research.
- The assistant has no approve endpoint by design; it cannot send or approve anything.
- Redis, Celery and scikit-learn from the original plan are not used and have been removed from `requirements.txt` and Docker Compose.
- JWTs use PyJWT. Each user has a `token_version`; changing the password bumps it and invalidates all earlier access/refresh tokens.
- The send loop claims each due campaign-lead with an atomic `UPDATE ... WHERE next_send_at <= now` before sending. A transient SMTP failure backs off 15 minutes instead of retrying every tick.
