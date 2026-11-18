# Changes, test results and known limitations

Baseline: commit "Baseline: original upload". See `PROJECT_ANALYSIS.md` for the findings numbered below.

## Fixed / added
| Finding | Change |
|---|---|
| 1 | Backend dependencies upgraded (FastAPI 0.164, Starlette 1.10, cryptography 50, python-multipart 0.0.34, dnspython 2.9, SQLAlchemy 2.1...). `python-jose` replaced by PyJWT (removes vulnerable `ecdsa`). `react-router-dom` 6 -> 7.18. `pip-audit`: 0 known vulnerabilities; `npm audit --omit=dev`: 0. |
| 2, 3 | Compose now sets `APP_ENV=production`, requires `SECRET_KEY`, `ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `PUBLIC_BASE_URL`, forces `SEED_DEMO_DATA=false`, no longer publishes the DB, drops unused Redis. Dockerfile: non-root user, `npm ci`, health check, `--proxy-headers`. |
| 4 | `production_problems()` blocks startup in production on weak secret, missing/invalid `ENCRYPTION_KEY`, demo seed, SQLite, localhost `PUBLIC_BASE_URL`. |
| 5 | `POST /auth/change-password`; per-user `token_version` revokes all older access/refresh tokens. Tokens must carry `exp`. UI: "Your account" card in Settings. |
| 6 | `ALLOW_REGISTRATION` setting + public `GET /auth/config`; login page hides sign-up when closed. |
| 7 | Atomic claim before every send (no double sends across workers/ticks); transient SMTP failures back off 15 min. A first version of the claim had a stale-row bug that sent a follow-up early; the new race test caught it and it is fixed. |
| 8 | In production, SMTP/IMAP hosts must resolve to public addresses; ports validated. |
| 9 | Login-failure tracker bounded (10,000 entries, expired entries pruned). |
| 10 | CRM: delete lead (managers/admins, confirm, API refuses leads with history); visible error when export fails; error boundary around every page. |
| 11 | Lazy-loaded pages: entry bundle 827 kB -> 298 kB (gzip 234 -> 99 kB); no more chunk-size warning. |
| 12 | Unused deps removed (celery, redis, scikit-learn, pandas); `requirements-dev.txt`; GitHub Actions CI (SQLite + PostgreSQL tests, pip-audit, build, npm audit). |
| 13 | Lead search treats `%` and `_` literally. |
| DB | Migration `0002`: `users.token_version`, indexes `ix_leads_org_status`, `ix_leads_org_score`, `ix_campaign_leads_due`, `ix_messages_org_dir_sent`. Verified up/down, with existing rows, on SQLite and PostgreSQL 16; zero model drift. |

## Test results (actually run)
| Check | Result |
|---|---|
| Backend tests, SQLite | 76 passed (59 original + 17 new) |
| Backend tests, PostgreSQL 16 | 76 passed |
| Backend line coverage | 81% |
| Alembic upgrade/downgrade/upgrade, autogenerate drift | clean on both databases |
| Browser E2E (`scripts/e2e_smoke.mjs`, Chromium vs. real server) | 30/30: login, all 14 pages with no JS/API errors, CSV export, lead create/delete, register, password change + token revocation, re-login, no horizontal overflow at 375 px on 6 pages |
| Production start guard | verified to refuse unsafe config and accept a valid one |
| `docker compose config` | refuses without secrets, valid with them |

## Known limitations (not verified / not done)
- **The Docker image was not built** (no Docker daemon in my environment). Compose syntax was validated; the Dockerfile has not been run. Build it once before relying on it.
- **Real mail was never sent.** SMTP/IMAP and the LLM provider were tested with mocks only; try "Test connection" with your mailbox.
- **Single process only**: the scheduler is in-process. Claiming prevents double sends, but scale-out is not supported.
- Access/refresh tokens live in browser `localStorage` (mitigated by a strict CSP); httpOnly cookies would be stronger but is a larger change.
- No frontend unit tests; UI is covered by the browser smoke script, which is not run by CI (needs a running server).
- Email checks confirm the domain accepts mail, not that the mailbox exists.
- Not added on purpose: notifications, websockets/real-time, extra analytics. They would not close a real gap in this app.
