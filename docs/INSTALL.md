# Mail Engine — Installation & Configuration

How to stand the system up, and — the part you asked for — **every variable you need to
collect** to run it, from a bare database to a live wave.

Two things to understand up front:

- **The app runs today on the database variables alone.** Everything above the vendor
  seams (Lob, PostHog, NeverMissCall, Anthropic) is fully functional against in-memory
  fakes. You can load a list, draft/preview/approve a wave, run the nightly judgment
  job, and browse the web window with nothing but Postgres.
- **The external credentials are needed only to go live** (a real drop, real response
  capture, AI-written briefs, delivered digests). Each sits behind a seam whose real
  client is deferred until you supply its credentials — none require code rework.

---

## 1. Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Docker + Docker Compose | any recent | runs the Postgres 15 container |
| `uv` | recent | Python dependency + venv manager |
| Python | 3.12 | the app runtime |

---

## 2. Local setup (runs on the database variables only)

```bash
cp .env.example .env          # then edit the values (see §3a)
make up                       # start Postgres 15, create the read-only role
make migrate                  # apply migrations 0001–0004
make test                     # full suite — proves the install
make run                      # the web window at http://localhost:8001
```

`make` targets: `up`, `down`, `migrate`, `run`, `test`, `lint`, `fmt`, `nuke` (`make help`).

> The app reads its two `*_DATABASE_URL`s straight from the process environment — there is
> no dotenv loader in the app itself. `make run` (like `make migrate`) sources `.env` first;
> a bare `uv run uvicorn web.api:app` only works if you export the variables yourself.

---

## 3. Variables to collect

### 3a. Database & roles — REQUIRED NOW (the only variables the code reads today)

These live in `.env` (gitignored — never commit real secrets). The Postgres container
reads the `POSTGRES_*`/`READONLY_*` set; the app reads only the two `*_DATABASE_URL`s.

| Variable | What it is | Where to get it | Read by |
|----------|-----------|-----------------|---------|
| `POSTGRES_USER` | owner DB username | you choose | container init |
| `POSTGRES_PASSWORD` | owner DB password | you choose (secret) | container init |
| `POSTGRES_DB` | database name | you choose | container init |
| `POSTGRES_PORT` | host port for Postgres (default 5433) | you choose | compose |
| `READONLY_USER` | read-only role name | you choose | container init |
| `READONLY_PASSWORD` | read-only role password | you choose (secret) | container init |
| `OWNER_DATABASE_URL` | full DSN for the owner role — **the only write path** | assembled from the above | `db/session.py` |
| `READONLY_DATABASE_URL` | full DSN for the read-only role — the analysis bypass | assembled from the above | `db/readonly.py`, query verbs |
| `DROP_PASSWORD` | password for the UI "Run drops" button (fail-closed: unset = button disabled) | you choose | `web/api.py` |

> In production, point the two `*_DATABASE_URL`s at your managed Postgres 15 and set
> strong passwords. The read-only role must have `SELECT` and nothing else (migration
> `0002` grants exactly that).

### 3b. External services — REQUIRED BEFORE WAVE 1 (one block per seam; client deferred)

The system defines a Protocol seam for each vendor; the real client is built when you
hand over its credentials. Collect these before the ghost wave / wave 1. *(Env-var names
are proposed — they're finalized when each client is built.)*

**Print — Lob** (`seams/print_api.py`)

| Collect | What it is | Where to get it |
|---------|-----------|-----------------|
| Lob **live** API key | authorizes real print/mail submission | Lob dashboard → API Keys |
| Lob **test** API key | for the test environment / dry runs | Lob dashboard → API Keys |
| Lob **webhook signing secret** | verifies delivery webhooks (printed/delivered/returned) | Lob dashboard → Webhooks |
| Return/from address | the physical return address on each piece | your business address |

**Web response — PostHog** (`seams/posthog.py`, **built 2026-07-12** — env names final)

| Collect | Env var | What it is | Where to get it |
|---------|---------|-----------|-----------------|
| PostHog **personal API key** | `POSTHOG_API_KEY` | authorizes the nightly HogQL pull (needs Query Read scope) | PostHog → Personal API Keys |
| PostHog **project id** | `POSTHOG_PROJECT_ID` | the project the `?r=` visits land in | PostHog → Project Settings |
| PostHog **host** | `POSTHOG_HOST` | query-API host (default `https://us.posthog.com`; note: NOT the `us.i.posthog.com` capture host) | your PostHog instance |
| `?r=` capture live | — | landing page records the mailer code as `?r=` | your landing page (wired; see landing-pages repo) |

**Phone response — NeverMissCall** (`seams/nmc.py`, deferred — your own product)

| Collect | What it is | Where to get it |
|---------|-----------|-----------------|
| Campaign **phone number** | the number printed on the postcards — **(888) 853-8575** (changed 2026-07-14 from 866-9044: that number is NMC's reserved full-life TEST CALLER — its Twilio `sms_url` must stay empty, so it can never answer campaign responders. 853-8575 is the live sales-AI line, TFV-approved) | your NMC / Twilio number |
| **"nevermisscall" vertical config** | the NMC config that runs the campaign line (ad-responder script, booking to the founders' calendar) | configured inside NMC |
| NMC **response API access** | credential to pull calls/SMS/bookings nightly | your NMC deployment |

**AI briefs — Anthropic** (`ai/client.py`, deferred — optional)

| Collect | What it is | Where to get it |
|---------|-----------|-----------------|
| `ANTHROPIC_API_KEY` | writes the 30-second nudge briefs | console.anthropic.com |

> Optional by design: with no client, the digest uses a deterministic template. AI
> improves the briefs; it is never required for delivery.

**Digest delivery — NMC sending path** (`seams/sender.py`, deferred — your own product)

| Collect | What it is | Where to get it |
|---------|-----------|-----------------|
| NMC **sending credential** | the SMS/email path that delivers the morning digest to each founder | your NMC deployment |
| Founder **contact points** | where Young's / the partner's digest goes (phone or email) | you decide |

**Data input (not a variable, but required)**

| Collect | What it is |
|---------|-----------|
| **Purchased lists** | CSLB contractor list, county FBN feeds (CA in hand). Each format goes through its adapter in `intake/` (e.g. `python -m intake.fbn_ca raw.csv --year 2026 -o out.csv`), then the canonical CSV loads via `load_list` / the `/intake` page |

### 3c. Operational config — HAS DEFAULTS (collect only to override)

These ship with sensible defaults in code; you don't need to collect anything to start.
They will move into a runtime config table later; today they're constants.

| Value | Default | Where | What it controls |
|-------|---------|-------|-----------------|
| Founder identities | `owner='young'`; recipient `YOUNG` | migration `0004`, judgment | who owns a contact / who gets a nudge (partner-owned contacts get `'partner'`) |
| Per-piece cost estimate | `73` ¢ | `service/waves.py` | preview cost estimate (until Lob's `cost_estimate` is wired) |
| Execute drift tolerance | `10%` | `service/execution.py` | how far the drop-time audience may drift from the approved size before `execute_wave` halts |
| `QUIET_DAYS` | 4 | `config/params.py` | quiet-conversation nudge threshold |
| `STALL_DAYS` | 14 | `config/params.py` | activation-stall churn alarm |
| `PARTIAL_DAYS` | 4 | `config/params.py` | setup-step-stuck threshold |
| `FAIL_PCT` | 8% | `config/params.py` | wave delivery-failure alarm |
| `RESP_CHECK_DAYS` | 10 | `config/params.py` | wave zero-response window |
| `LEAD_DAYS` | 3 | `config/params.py` | wave-approval-slipping lead time |
| `AGE_OUT_DAYS` | 30 | `config/params.py` | lost-aging threshold |
| `NUDGE_BUDGET` | 5/day | `config/params.py` | max nudges per founder per day |
| `COOLDOWN_DAYS` | 3 | `config/params.py` | per-contact re-nudge cooldown |
| `EXPIRE_DAYS` | 5 | `config/params.py` | stale next-action expiry |
| `ORPHAN_MAX` | 20 | `config/params.py` | unattributed-event alarm threshold |

---

## 4. Collection checklist

**To run locally / test (today):**
- [ ] The eight §3a database variables in `.env`

**To go live (wave 1):**
- [ ] Lob: live key, test key, webhook signing secret, return address
- [ ] PostHog: project key, personal key, host, `?r=` capture wired on the landing page
- [ ] NMC: campaign phone number, "nevermisscall" vertical config, response API access
- [ ] NMC sending: digest delivery credential + each founder's contact point
- [ ] Anthropic API key *(optional — improves briefs)*
- [ ] CSLB list (CSV)
- [ ] Confirm/adjust the §3c defaults if any don't fit

---

## 5. Operational notes

- **Backups:** nightly `pg_dump` to offsite storage; the `events` table is the
  business's memory. Test a restore before wave 1.
- **Deploy:** run `uvicorn web.api:app` behind your reverse proxy (private network /
  basic auth — there is no app-level auth by design, two founders only).
- **Jobs:** schedule `jobs/nightly.run_nightly` (sync → resolve → recompute → judgment)
  once a day, after the response feeds are quiet; and `jobs/drop.run_drops` when a wave
  is due.
- **Migrations:** `make migrate` applies `0001`–`0004`; re-running is idempotent.
