# AI Outreach Pro: Phase 1 Project Analysis

Analysis of the uploaded project **before any change was made**. Baseline is Git commit `Baseline: original upload`.

## 1. What the project is

A multi-tenant B2B outreach platform: lead import and discovery, website research, lead scoring, AI email writing, approval-gated campaigns, follow-ups, inbox and reply classification, CRM, analytics and an assistant.

| Layer | Stack |
|---|---|
| Backend | FastAPI 0.115, SQLAlchemy 2, Alembic, Pydantic v2, APScheduler (in-process), JWT, bcrypt, Fernet |
| Frontend | React 18, Vite 5, Tailwind 3, React Router 6, TanStack Query, Recharts |
| DB | SQLite (dev/tests), PostgreSQL (production) |
| Size | ~7,400 lines, 17 routers, 16 services, 14 pages, 59 tests |

## 2. Baseline measurements (actually run)

| Check | Result |
|---|---|
| `pytest` | 59 passed |
| `vite build` | Success; one 827 kB JS chunk (warning) |
| Alembic `upgrade head` on empty DB, compared with models | 0 schema differences |
| Frontend API calls vs. backend routes (74 calls) | All resolve (1 dynamic `/campaigns/{id}/{action}` call maps to real routes) |
| `pip-audit` | Known CVEs in `starlette`, `python-multipart`, `cryptography`, `dnspython`, `ecdsa` (via `python-jose`), `pytest` |
| `npm audit --omit=dev` | 2 moderate issues in `react-router` 6.x |

**Conclusion:** the README's claim that all phases are done is largely true. The functional core works and is tested. The problems are mainly in dependency security, deployment defaults, account security and a few missing UI paths.

## 3. Strengths to preserve (verified by reading the code)

- Human-approval gate on campaigns; compliance re-checked at send time (suppression, opt-out, address, limits).
- Tenant isolation checks (`org_id`) on lead, integration and user access.
- SSRF protection in the website fetcher (blocks private IPs on every redirect), robots.txt, throttling.
- CSV/XLSX formula-injection protection; Fernet-encrypted mailbox credentials; audit log.
- Unsubscribe page uses GET-confirm and POST-act (safe from mail scanners); RFC 8058 headers.
- Login rate limiting, security headers/CSP, generic 500 handler.

## 4. Findings

Severity: **H** high, **M** medium, **L** low.

| # | Sev | Area | Finding |
|---|---|---|---|
| 1 | H | Dependencies | Pinned backend packages have known vulnerabilities (starlette, python-multipart, cryptography, dnspython; `python-jose` pulls in vulnerable `ecdsa` and is poorly maintained). |
| 2 | H | Deployment | `docker-compose.yml` does not set `APP_ENV=production`, so the production secret check is bypassed. It defaults to the public placeholder `SECRET_KEY` and `SEED_DEMO_DATA=true` (a known demo login `Demo1234!`). |
| 3 | M | Deployment | Compose publishes PostgreSQL (`postgres/postgres`) and Redis on host ports. Redis and Celery are never used by any code. |
| 4 | M | Secrets | In production, a missing `ENCRYPTION_KEY` silently falls back to a key derived from `SECRET_KEY`; rotating the secret then makes all stored mailbox passwords unreadable. |
| 5 | M | Auth | No way to change a password; no way to invalidate sessions (refresh tokens live 14 days and survive a password reset or user deactivation until they expire; deactivation is checked, password change is not possible at all). |
| 6 | M | Auth | Open self-registration cannot be turned off on a private deployment. |
| 7 | M | Reliability | Send loop has no atomic claim. If more than one process runs the scheduler (several workers/replicas), the same email can be sent twice. A failing SMTP send is also retried on every 60 s tick. |
| 8 | M | Security | Mailbox SMTP/IMAP host is not checked, so a manager could make the server connect to internal addresses (blind SSRF). |
| 9 | L | Auth | Login failure tracker is an unbounded in-memory dict. |
| 10 | L | UX | Leads cannot be deleted from the UI although the API supports it; no account page; no error boundary (a render error blanks the app). |
| 11 | L | Performance | Whole UI ships as one 827 kB bundle. |
| 12 | L | Quality | Unused dependencies (celery, redis, scikit-learn, pandas, openai SDK is used lazily); deprecation warnings from `python-jose`; no frontend tests; no CI definition. |
| 13 | L | Search | `%` and `_` typed into lead search act as SQL wildcards (not an injection; the query is parameterized). |
| 14 | Info | Docs | `ARCHITECTURE.md` mentions Celery/Redis/scikit-learn as planned stack; README test count and "Tests" section duplicated. |

## 5. Not changed, by design

- Open items that need your decision are listed in the final report (e.g. multi-instance deployment, SMTP vs Gmail OAuth).
- No fake data or placeholder features were added. Features were added only where they close a real gap above.
