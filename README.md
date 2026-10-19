# AnswerScope — AEO (Answer Engine Optimization) MVP

AnswerScope shows how visible a brand is in AI-generated answers and what to improve.

1. **Website audit**: crawls the site's public pages, respects robots.txt, and checks titles, descriptions, headings, structured data, FAQ content, sitemap, AI crawler access and coverage of common customer questions.
2. **Question generation**: produces 20 questions buyers might ask an AI assistant. It uses the configured LLM if there is one, and deterministic templates otherwise.
3. **AI visibility tests**: sends each question to a real AI provider (Anthropic Claude, optionally with web search). For each answer it records brand mentions, website citations and competitor mentions, with evidence.
4. **Dashboard, competitor comparison and history**: all of these are computed from recorded results.
5. **Action plan + fix generator**: prioritized fixes with status tracking, plus ready-to-review drafts (meta tags, schema, FAQ, comparison and pricing pages, sitemap.xml, robots.txt) grounded only in the site's own content.

Each user has a private account; AI usage is capped per user and globally to protect the server's API key.

Nothing is simulated. If no provider API key is configured, visibility tests are disabled and the UI says so. The audit still works.

---

## Quick start (local)

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip), Node 20+, PostgreSQL 12+.

### 1. Database

```bash
DB_PASSWORD=$(openssl rand -hex 24)   # a strong random password; put it in backend/.env in the next step
sudo -u postgres psql -c "CREATE USER aeo WITH PASSWORD '$DB_PASSWORD';" -c "CREATE DATABASE aeo OWNER aeo;"
echo "DATABASE_URL=postgresql+psycopg://aeo:$DB_PASSWORD@localhost:5432/aeo"   # copy this line into backend/.env
```

### 2. Backend (FastAPI, port 8000)

```bash
cd backend
cp .env.example .env          # then edit DATABASE_URL / ANTHROPIC_API_KEY
uv sync                       # or: python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
uv run alembic upgrade head   # create tables
uv run uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 3. Frontend (Next.js, port 3000)

```bash
cd frontend
cp .env.example .env.local    # BACKEND_URL=http://127.0.0.1:8000
npm install
npm run dev                   # or: npm run build && npm start
```

Open http://localhost:3000, click **Sign up** to create an account (the first account also takes ownership of any projects created before accounts existed), then click **New project** and follow the Workflow card on the dashboard.

Optional: to analyze JavaScript-only sites (React/Vite apps that serve an empty `<div id="root">`), install the headless browser once:

```bash
cd backend && uv run playwright install chromium-headless-shell
```

Playwright is pinned to 1.55.0 because it is the last release that supports Ubuntu 20.04 (the default WSL image). On a newer OS you can raise the pin.

### Tests

```bash
cd backend && uv run pytest     # 132 tests: URL safety/SSRF, fetch failures, crawler, audit scoring, detection, metrics, provider, API
cd frontend && npm run lint && npm run build
```

Tests use in-memory SQLite and mocked network and provider calls, so they never touch the internet or real credentials.

---

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | none (required) | PostgreSQL connection, e.g. `postgresql+psycopg://aeo:<password>@localhost:5432/aeo`. Keep it only in `backend/.env` |
| `CORS_ORIGINS` | `http://localhost:3000` | Origins allowed to call the API directly. Not needed with the default `/api` proxy |
| `ANTHROPIC_API_KEY` | empty | Enables AI question generation and visibility tests |
| `AEO_ANTHROPIC_MODEL` | `claude-opus-5-5` | Model used for answers |
| `AEO_ANTHROPIC_EFFORT` | `medium` | `low` … `max`; trades depth for cost/latency |
| `AEO_ANTHROPIC_WEB_SEARCH` | `true` | Let Claude search the web (needed to observe citations) |
| `AEO_ANTHROPIC_WEB_SEARCH_MAX_USES` | `3` | Searches per question |
| `AEO_ANTHROPIC_SERVER_FALLBACKS` | `true` | If a request is declined by safety classifiers, Anthropic retries it on a fallback model. The model that actually answered is recorded on each answer. |
| `AEO_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | API endpoint |
| `CRAWL_MAX_PAGES` / `CRAWL_TIMEOUT_SECONDS` / `CRAWL_MAX_BYTES` | 15 / 10 / 2 MB | Crawl limits |
| `CRAWL_MAX_SECONDS` | 120 | Total crawl time budget. The audit completes with the pages fetched so far |
| `VISIBILITY_MAX_QUESTIONS` | 20 | Questions per visibility run |
| `ALLOW_REGISTRATION` | `true` | Allow new sign-ups |
| `COOKIE_SECURE` | `false` | Send the session cookie only over HTTPS (set `true` in production) |
| `SESSION_DAYS` | 30 | Session lifetime |
| `QUOTA_VISIBILITY_RUNS_PER_USER_PER_DAY` / `_GLOBAL_PER_DAY` | 3 / 20 | AI visibility tests per user / across all users, rolling 24 h |
| `QUOTA_QUESTION_GENERATIONS_PER_USER_PER_DAY` / `_GLOBAL_PER_DAY` | 10 / 100 | AI question generation (templates are free) |
| `QUOTA_FIX_GENERATIONS_PER_USER_PER_DAY` / `_GLOBAL_PER_DAY` | 20 / 200 | AI fix drafts (template drafts are free) |
| `RATE_LIMIT_AUTH_PER_MINUTE` / `RATE_LIMIT_WRITES_PER_MINUTE` | 10 / 30 | Login attempts per IP; write requests per user |
| `JOB_MODE` | `inline` | `inline`: jobs run inside the API (local). `worker`: run `python -m app.worker` separately (production) |
| `RENDER_JS` / `RENDER_MAX_PAGES` / `RENDER_TIMEOUT_SECONDS` | `true` / 8 / 20 | Render JavaScript-only pages in headless Chromium |

Notes:
- Only the API key uses the SDK's standard name. The other provider options are `AEO_`-prefixed on purpose, so variables exported for other tools (for example `ANTHROPIC_MODEL` or `ANTHROPIC_BASE_URL` in your shell) can't silently change test conditions.
- **`backend/.env` takes priority over environment variables.** A variable exported in your shell (for example an `ANTHROPIC_API_KEY` set for another tool) can't override it. Settings not listed in `.env` still fall back to the environment, then to defaults.
- Keys are read only by the backend. They are never returned by the API, never logged, and never shipped in the frontend bundle.

### Frontend configuration (`frontend/.env.local`)

| Variable | Default | Purpose |
|---|---|---|
| `BACKEND_URL` | `http://127.0.0.1:8000` | Where the Next server proxies `/api/*`. Server-side only. For `next build`/`next start` it is read at build time |
| `DEV_ALLOWED_ORIGINS` | empty | Extra hostnames allowed to open the dev server. This machine's own IP addresses are allowed automatically |
| `NEXT_PUBLIC_API_URL` | unset | Only for calling a separately hosted API directly from the browser. That API's `CORS_ORIGINS` must then include the frontend's origin |

The browser always talks to the frontend's own origin (`/api/...`) and Next forwards those requests to the backend. The app therefore works the same whether you open `localhost:3000`, the "Network" address that `next dev` prints (for example the WSL IP), or a LAN hostname. No CORS setup is needed.
- Cost: with web search on, a 20-question run makes 20 or more Messages API calls plus web searches. Lower `AEO_ANTHROPIC_EFFORT` or `VISIBILITY_MAX_QUESTIONS` to reduce cost.

---

## Architecture

```
frontend/ (Next.js 16 App Router + Tailwind v4, client-side data fetching)
  src/app/                 landing, projects, new project, project tabs:
                           dashboard · audit · results · competitors · recommendations · history · settings
  src/lib/api.ts           typed API client
  src/components/          UI kit, project context (polls while jobs run), provider notices

backend/ (FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2)
  app/crawler/url_safety.py   URL normalization + SSRF guards (scheme, credentials, local hosts, private IPs)
  app/crawler/fetcher.py      safe fetcher: DNS-pinned connections, per-hop redirect validation, size/time limits
  app/crawler/crawler.py      robots.txt, sitemap.xml, prioritized same-site crawl
  app/analysis/extract.py     HTML → title, meta, headings, links, text, JSON-LD/microdata, FAQ detection
  app/analysis/audit.py       weighted checks, page issues, topic coverage (unanswered questions)
  app/questions/generator.py  LLM questions (structured output) + deterministic template fallback
  app/providers/              adapter interface, Anthropic implementation, registry
  app/visibility/detection.py mention / citation detection with evidence
  app/visibility/metrics.py   metric calculations
  app/recommendations/engine.py  evidence-backed, prioritized recommendations
  app/services/jobs.py        background audit & visibility jobs (FastAPI BackgroundTasks)
  app/api/routes.py           REST API
  alembic/                    migrations
```

**Jobs.** Audits and visibility runs execute in FastAPI's background thread pool. Progress is stored in the database and the UI polls it. Jobs that are still running when the server stops are marked failed on the next startup. Provider calls run three at a time.

**Data model.** `projects`, `competitors`, `website_audits`, `audit_pages`, `questions` (with `source` = `llm` or `template`), `visibility_runs` (with a `conditions` snapshot), `provider_answers`, `mentions` (each brand or competitor mention or citation, with evidence) and `recommendations`. Constraints include CHECKs on status, priority and kind values, unique keys (for example, one answer per question per run), and cascading foreign keys.

### Metric definitions

Metrics come only from the answers recorded in a single completed run. Failed questions are excluded, and a rate is shown as "—" when there are no answers to compute it from.

- **Questions tested**: answers the provider returned successfully.
- **Brand mention rate**: the share of tested answers that name the brand. A match is a whole word, case-insensitive, and outside URLs. It can be the name itself, a compact form without spaces, or the domain. Single-word names must be capitalized (so "apple" ≠ Apple).
- **Website citation rate**: the share of tested answers whose provider-cited sources, or links in the answer text, include a URL on the brand's domain or a subdomain. Search results the model retrieved but didn't cite don't count.
- **Competitor visibility**: the same two rates per competitor, measured on the same answers. Citations are tracked only for competitors that have a website on file.
- **Share of voice**: the brand's mentioning answers divided by the mentioning answers of all tracked brands.
- **Audit score**: 100 × Σ(weight × check score) / Σ weights. Page-level checks score the fraction of crawled pages that pass.

### Action plan

Recommendations form a persistent action plan. Each item has a stable key, so its status survives re-audits.

- **Status:** open, planned, in progress, completed or dismissed, with an optional note (`PATCH /api/recommendations/{id}`).
- **Ordering:** blocking root causes come first (for example, an empty JavaScript homepage). After that, items are ordered by impact × confidence ÷ effort, so quick wins rise to the top.
- **Verification:** every item says how to check the fix. After each audit or visibility test:
  - an item that is no longer found moves to **No longer detected**;
  - an item marked completed but still found shows a warning;
  - an item that comes back is re-detected, not duplicated.
- **Not falsely resolved:** an item is only marked resolved if the new data actually re-checked it. For example, content checks are skipped while the homepage is a JavaScript shell.

### Retest and compare

After making changes, **Retest** asks the AI the exact same questions as an earlier run (`POST /api/runs/{id}/retest`, which counts against the visibility-test quota). **Compare** (`GET /api/projects/{id}/compare?base=&target=`) puts two completed runs side by side:

- **Like-for-like:** only questions answered in both runs are compared (matched by text), so a changed question set can't look like a visibility change.
- **What you see:** changes in unprompted mentions, overall mentions, citations, "AI knows you" and each competitor's mention rate, in percentage points and in numbers of answers. It also lists every question that gained or lost a mention, citation or competitor, and the action items a re-audit stopped detecting between the two runs.
- **Honesty guards:**
  - Runs with a different provider, model, effort, web-search setting, system prompt or competitor list are flagged as not directly comparable.
  - A change of one answer is labelled as possibly normal variation.
  - The page states that it shows *what* changed, not *why*.

### Competitor comparison is like-for-like

Each run stores its provider, model, settings, competitor list and question IDs in `conditions`. Comparisons are only made within one run. History shows each run's conditions, because runs with different models or settings aren't directly comparable.

---

## Adding an AI provider

1. Create `backend/app/providers/<name>_provider.py` with a subclass of `AIProvider` (see `base.py`):
   - `is_configured()`, `setup_instructions()`, `model`
   - `answer(question) -> ProviderAnswer(text, model, sources=[{url, title, type: "cited"|"search_result"}])`
   - optionally `complete_json(system, prompt, schema)` for question generation
   - `conditions()`: everything that affects answers (it is stored with the run)
   - raise `ProviderError(message, fatal=..., retryable=...)` on failures. `fatal` aborts the run (for example, bad credentials).
2. Register it in `PROVIDER_FACTORIES` in `app/providers/registry.py` and add its settings to `app/config.py`.
3. Use the official SDK for that provider. Detection, metrics, storage and UI work unchanged. The UI's run button currently starts the `anthropic` provider; add a selector once there is more than one.

---

## Deploying to production

`docker-compose.yml` runs the production stack: Postgres, the API, a **separate job worker**, and the Next.js frontend as a standalone server.

```bash
cp .env.production.example .env.production   # set POSTGRES_PASSWORD and ANTHROPIC_API_KEY
docker compose --env-file .env.production up -d --build
```

- **Only the frontend (port 3000) is published.** The API is reachable only from the frontend container, which proxies `/api`. That also means the `X-Forwarded-For` header used for rate limiting comes from your own proxy.
- **Put HTTPS in front** (Caddy, nginx or a cloud load balancer). The stack sets `COOKIE_SECURE=true`, so session cookies are only sent over HTTPS (browsers also accept them on `http://localhost`).
- **Jobs run in the worker** (`JOB_MODE=worker`). The API only queues audits and visibility tests in the database, and the worker claims them with `FOR UPDATE SKIP LOCKED`, so jobs survive API restarts and you can run several workers. If a worker dies mid-job, that job is marked failed when a worker next starts.
- **Migrations** run automatically when the API container starts (`alembic upgrade head`).
- **Spend control:** set the `QUOTA_*` limits to match your budget. `ALLOW_REGISTRATION=false` closes sign-ups, for example for a private beta.
- The backend image includes headless Chromium for JavaScript rendering.

For a managed setup, the same split works elsewhere: frontend on Vercel or a Node host (set `BACKEND_URL` at build time), API and worker as two services from `backend/Dockerfile` (the worker's command is `python -m app.worker`), and managed Postgres.

## Security

- **SSRF protection.** Only http/https URLs are accepted, and URLs with embedded credentials are rejected. Localhost, `.local`/`.internal`, and private, loopback, link-local, CGNAT, reserved and multicast IPs are refused (including IPv4-mapped IPv6). Every hostname is resolved and **all** of its addresses must be public. The connection then goes to the vetted IP, with the Host header and TLS SNI set to the hostname, so DNS rebinding can't redirect it. Every redirect hop is validated again. Crawls stay on the audited site.
- **Limits.** 10 s timeouts, a 2 MB response cap, 5 redirects, a page cap, a polite delay (honoring robots `Crawl-delay` up to 2 s), and no use of environment proxies.
- **robots.txt.** Disallowed pages are skipped and reported. If the homepage itself is disallowed, the audit stops.
- **Input validation.** Inputs are validated with Pydantic: name lengths, at most 10 competitors, de-duplication, URL normalization.
- **Accounts.** Passwords are hashed with scrypt (salted). Sessions are random 256-bit tokens in an `httpOnly`, `SameSite=Lax` cookie (`Secure` with `COOKIE_SECURE=true`); only a SHA-256 hash of each token is stored. Every API object is looked up through its project's owner, and other users' objects return 404 so IDs can't be probed. Login responses don't reveal whether an email has an account.
- **Cost protection.** AI actions (visibility tests, AI question generation, AI fix drafts) are capped per user and globally per rolling 24 hours (`QUOTA_*` settings). Template outputs are free. Login attempts and write requests are rate-limited.
- **JavaScript rendering.** The headless browser gets its own SSRF guard. Every browser request is intercepted, and only http(s) requests to the audited site (and its subdomains) that pass the public-IP check are allowed. Third-party requests, images, media and fonts are blocked. The site's hostname is pinned to its vetted IP inside Chromium, service workers are blocked, and page count and time are capped.
- **Fix drafts.** AI drafts see only the crawled site text and must use placeholders for missing facts. Any number in a draft that doesn't appear on the site is flagged for review. Drafts are never applied automatically.

## Troubleshooting

- **Submitting a URL does nothing.** If you open the dev server from a hostname that isn't this machine (a tunnel or custom domain), add it to `DEV_ALLOWED_ORIGINS` and restart `npm run dev`. Next only serves its scripts to allowed origins, and the form stays disabled ("Loading…") until they load.
- **"Cannot reach the backend API".** Start the backend with `uv run uvicorn app.main:app --port 8000`, or point `BACKEND_URL` at it.
- **An audit failed.** The audit tab shows the reason and a code: `blocked` (HTTP 401/403), `rate_limited` (429), `bot_protection` (a challenge page such as Cloudflare), `robots_disallowed`, `timeout`, `connection`, `http_error`, `not_html` or `unsafe_url`. Failed audits never get a score.

## Known limitations

- Sites that block automated clients (Cloudflare or other bot protection, HTTP 403) can't be audited. The crawler identifies itself honestly as `AEOAuditBot` and does not try to bypass protections.
- JavaScript-only pages are rendered in a headless browser when Playwright's Chromium is installed (up to `RENDER_MAX_PAGES` per audit). Without it, those pages look empty, as they do to most AI crawlers. Rendering only loads the audited site's own resources, so content fetched from third-party APIs won't appear.
- Topic coverage and FAQ detection use heuristics on URLs, titles and headings of the crawled sample (15 pages by default), so they can miss content on pages that weren't crawled.
- Mention detection is string matching. Ambiguous brand names can still produce false positives or negatives. The evidence snippets are shown so you can verify each one.
- API answers are not the same as consumer ChatGPT, Claude, Gemini or Perplexity, which add personalization, memory and different search stacks. Answers also vary between runs.
- There is one provider so far (Anthropic). Accounts are email + password only; there is no password reset or email verification yet.
- The rate limiter is in-memory, so each API process limits independently. Behind several API processes, add a shared limiter (for example at the reverse proxy). Quotas are database-backed and global.
- Recommendations are rule-based and are rebuilt from the latest audit and run. They improve clarity and coverage but **do not guarantee** AI mentions, citations or rankings.
