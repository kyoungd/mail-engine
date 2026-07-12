# Direct Mail AI — Data Document

*NeverMissCall mail engine. Covers data flow, schema, and data governance. Companion to the product description and architecture overview.*

---

## 1. Data flow

The organizing principle: **everything flowing in is a fact, everything flowing out is a judgment**, and the database in the middle is where facts become judgments.

### Inflows

| Source | Tempo | Nature |
|---|---|---|
| Purchased lists (CSLB, county FBN feeds, …) | One-time bulk load per list, via a per-format intake adapter (`intake/`) | Cleaned at intake (dedupe on adapter-prefixed `list_key`, NCOA/CASS); never trusted as fresh afterward. Per-list shapes, coverage facts, and filter traps: [list-shapes.md](list-shapes.md) |
| Lob webhooks | Real-time, per piece | Printed / delivered / returned — the denominator of every response rate |
| PostHog | Nightly pull | Web response: landing visits, funnel steps, keyed by `?r=` mailer code |
| NeverMissCall | Nightly pull | Phone response: calls, SMS threads, bookings from the dogfooded campaign line |
| Voice notes | Ad hoc, human | Demo impressions, partner conversations; AI structures raw notes into events |

Nightly cadence for PostHog/NMC is a choice, not a limitation — direct mail unfolds over days; a 12-hour-stale number changes no decision. Voice notes are the only inflow requiring human discipline and are deliberately frictionless, because unstructured residue is the leak point: AI reasons well over clean state and badly over gaps.

### The join

Everything meets on the **mailer code** — the thread from physical postcard to QR scan to landing visit. Phone response joins on a secondary key, the caller's **normalized phone number**, matched to the contact; the mailer code confirms which piece prompted the call where recoverable. Attribution keys live on *pieces*, not contacts: a contact receives many pieces, and per-piece codes are what distinguish "drop 2 worked" from "drop 1 landed late."

### Raw vs. derived (the load-bearing decision)

- **Raw events** are facts: append-only, never edited, kept forever. "Piece 4471 delivered June 3." "Inbound call, missed, SMS flow engaged."
- **Contact state** is interpretation: wave-2 non-responder, went quiet mid-conversation, customer pending calendar connection. Derived from events, stored only as a recomputable snapshot.

If the definition of "responded" changes later, rerun the derivation over history and every past wave's numbers update under the new definition. Systems that store only conclusions can never change their mind; this one can. This property is what makes the information-buying posture real.

### Outflows and presentation

Three outflows map to three kinds of questions:

- **Anticipatable, answerable from state** → web UI (pull): wave status, approval queue, pipeline view.
- **Questions the system should ask itself** → push nudges: the nightly judgment job reads contact state and sends "these two went quiet after pricing questions — today's the day" to a founder's phone. Nobody checks anything; the system interrupts only when a human action is due.
- **Questions nobody anticipated** → conversational surface: Claude Code querying the events table directly — possible precisely because raw history survived.

Plus the one physical outflow: approved wave definitions leaving as print instructions — the only path where data acts on the world, and the only one gated by a human button.

**Presentation rule:** humans never supply state twice and never hunt for what the system already knows. Facts flow in once at the source; what flows out is a rendered view, a judgment, or a prose answer. Re-typing something the system witnessed, or scrolling a table to decide what to do next, is a design bug.

---

## 2. Schema

Six tables. Two principles: attribution keys live on pieces, not contacts; anything that is a judgment is derived from events and stored only as a recomputable cache.

### Design rationale by table

**`pieces` — the attribution atom.** One row per physical card: contact, wave, variant, unique `mailer_code`, cost in cents. Cost-per-response becomes a join, not a spreadsheet. `unique (contact_id, wave_id)` hard-guarantees no double-mailing regardless of audience-rule bugs.

**`events` — append-only and deliberately dumb.** Source, type, timestamp, raw jsonb payload; no interpretation at write time. `contact_id`/`piece_id` nullable because attribution can lag reality — an inbound call arrives as just a phone number; a later resolution pass matches it. No fact is ever dropped for want of a join. `unique (source, external_id)` makes sync jobs idempotent: re-runs insert nothing twice.

**`waves.audience_rule` — data, not code.** The audience is a stored, reviewable filter evaluated at execution time. What is approved in the UI is exactly what fires; the piece rows created at execution are the permanent record of who the rule resolved to that day. `approved_audience_count` records the resolved size at approval so `execute_wave` can halt when the drop-time audience has drifted beyond tolerance from what a human approved.

**`variants.hypothesis` — required on purpose.** One line: what this creative tests. A variant without a hypothesis is decoration; the wave readout quotes the hypothesis back against the numbers.

**`contacts.stage_snapshot` — named to remind you it's a cache.** Truth is the event stream; the snapshot serves the UI and judgment job. `next_action_at` is the judgment job's output slot — the single column the push-nudge system runs on. `do_not_mail` is the only human-authored flag: suppression by request is a fact, not a derivation.

**`activation` — the sale's real finish line.** One row per won customer, three timestamps (forwarding, calendar, first lead captured). `first_lead_at IS NULL` past ~14 days after signup is the churn alarm — the single most valuable push nudge in the system.

Deliberate omissions: no `users` table (two founders need no auth rows), no `notes` table (notes are `source='human'` events — a notes table is how CRM-shape creeps back in).

### DDL

```sql
-- Mail Engine schema (Postgres 15+)

create extension if not exists "pgcrypto";

create type contact_stage as enum (
  'prospect', 'in_sequence', 'responded', 'in_conversation',
  'won', 'lost', 'suppressed'
);

create type wave_status as enum ('draft', 'approved', 'executing', 'sent', 'cancelled');

create type piece_status as enum ('created', 'submitted', 'printed', 'in_transit',
                                  'delivered', 'returned', 'failed');

create type event_source as enum ('lob', 'posthog', 'nmc', 'human', 'system');

create table contacts (
  id                uuid primary key default gen_random_uuid(),
  list_key          text unique,   -- per-list dedupe key, adapter-prefixed ('cslb-123456', 'fbn-ca-2024023299')
  business_name     text,
  contact_name      text,
  trade             text,          -- nullable: unknown for non-trade lists (FBN); such rows target by segment/source
  license_class     text,
  phone_e164        text,
  email             text,
  addr_line1        text,
  addr_line2        text,
  addr_city         text,
  addr_state        text,
  addr_zip          text,
  addr_validated_at timestamptz,
  segment           text,
  source            text not null default 'cslb',
  stage_snapshot    contact_stage not null default 'prospect',
  stage_computed_at timestamptz,
  next_action_at    date,
  next_action_note  text,
  do_not_mail       boolean not null default false,
  do_not_text       boolean not null default false,
  owner             text not null default 'young',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index contacts_phone_idx   on contacts (phone_e164);
create index contacts_stage_idx   on contacts (stage_snapshot);
create index contacts_segment_idx on contacts (segment, trade);
create index contacts_nudge_idx   on contacts (next_action_at)
  where next_action_at is not null;

create table variants (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  hypothesis  text not null,
  creative    jsonb not null,
  created_at  timestamptz not null default now()
);

create table waves (
  id             uuid primary key default gen_random_uuid(),
  name           text not null unique,
  drop_number    int  not null,
  audience_rule  jsonb not null,
  variant_split  jsonb not null,
  status         wave_status not null default 'draft',
  scheduled_for  date,
  approved_by    text,
  approved_at    timestamptz,
  approved_audience_count int,
  executed_at    timestamptz,
  created_at     timestamptz not null default now()
);

create table pieces (
  id           uuid primary key default gen_random_uuid(),
  contact_id   uuid not null references contacts(id),
  wave_id      uuid not null references waves(id),
  variant_id   uuid not null references variants(id),
  mailer_code  text not null unique,
  lob_id       text unique,
  status       piece_status not null default 'created',
  cost_cents   int,
  submitted_at timestamptz,
  delivered_at timestamptz,
  created_at   timestamptz not null default now(),
  unique (contact_id, wave_id)
);

create index pieces_contact_idx on pieces (contact_id);
create index pieces_wave_idx    on pieces (wave_id, variant_id);

create table events (
  id           bigint generated always as identity primary key,
  contact_id   uuid references contacts(id),
  piece_id     uuid references pieces(id),
  source       event_source not null,
  type         text not null,
  occurred_at  timestamptz not null,
  ingested_at  timestamptz not null default now(),
  external_id  text,
  payload      jsonb not null default '{}',
  unique (source, external_id)
);

create index events_contact_idx    on events (contact_id, occurred_at);
create index events_piece_idx      on events (piece_id);
create index events_type_idx       on events (type, occurred_at);
create index events_unmatched_idx  on events (source, occurred_at)
  where contact_id is null;

create table activation (
  contact_id       uuid primary key references contacts(id),
  signed_up_at     timestamptz not null,
  forwarding_at    timestamptz,
  calendar_at      timestamptz,
  first_lead_at    timestamptz,
  notes            text
);

create index activation_stalled_idx on activation (signed_up_at)
  where first_lead_at is null;
```

---

## 3. Governance — the data topics the schema alone doesn't settle

### Event type taxonomy (canonical vocabulary)

Sync jobs and the judgment job must agree on event names, or derivations silently miss facts. Namespaced `noun.verb`, fixed set, extended deliberately:

`piece.submitted` · `piece.delivered` · `piece.returned` — `page.visit` · `page.cta_click` — `call.inbound` · `call.missed` · `call.answered` — `sms.inbound` · `sms.outbound` — `demo.booked` · `demo.held` · `demo.no_show` — `signup.completed` — `note.demo_call` · `note.partner` · `note.general` — `contact.opt_out` · `contact.lost` — `nudge.sent`

New types require adding to this list first; the sync jobs reject unknown types rather than inventing them.

### Identity resolution precedence

When an event arrives unattributed, match in this order and stop at the first hit:
1. `mailer_code` in payload → piece → contact (strongest; also attributes the piece)
2. `external_id` continuity (same NMC conversation thread as an already-matched event)
3. `phone_e164` exact match after normalization
4. Otherwise: store unmatched; surface in a weekly "orphan events" query rather than guessing

Never fuzzy-match on name or address. A wrong attribution poisons response data silently; an orphan event is visible and fixable.

### Derivation definitions (state the interpretations explicitly)

- **responded** = any of `page.visit`, `call.inbound`, `sms.inbound` attributed to the contact after first `piece.submitted`.
- **went_quiet** = last inbound event > N days ago while stage is `in_conversation` (N=4 initially; a parameter, not a constant).
- **suppressed** = `do_not_mail` OR two consecutive `piece.returned` OR `contact.opt_out`.
- **lost** = a `contact.lost` event (human judgment the conversation is over) with no inbound after it. Revivable: an inbound landing after the latest `contact.lost` un-loses the contact, returning them to the pipeline. Distinct from `suppressed`, which is absorbing.
- These live in one place in code (the derivation module), versioned, so recomputation over history is always possible.

### Compliance (California operation, phone-heavy channels)

- **SMS/TCPA:** the campaign line's SMS-back flow responds to inbound calls — that's a solicited reply, but honor STOP instantly (`contact.opt_out` event + `do_not_text` flag) and never initiate cold outbound texts to the CSLB list. Texting cold numbers from a purchased list is a TCPA lawsuit generator; mail is the cold channel, SMS is the warm one.
- **CCPA:** the CSLB list is public record, but once enriched with behavioral events it's personal information. Deletion request = hard-delete contact row + anonymize (not delete) their events: keep the facts for aggregate wave math, sever the identity.
- **Do-not-mail hygiene:** honor requests immediately and permanently; `do_not_mail` survives recomputation by design.

### Operational data care

- **Backups:** nightly `pg_dump` to offsite object storage; the events table is the business's memory and is unrecoverable from anywhere else. Test a restore once before wave 1, not after a disaster.
- **Phone normalization:** E.164 at every ingestion point, one shared function; the identity-resolution chain depends on it.
- **Address decay:** re-validate addresses (CASS) before wave 2 and 3 for any contact whose wave-1 piece returned; returns are data, not just waste.
- **Cost data completeness:** postage + print cost lands on every piece at submission; partial cost data makes every efficiency metric a lie.

---

*Next documents: service layer contract (the verbs UI and Claude Code both call), judgment job rule set (the nightly query that fills `next_action_at`).*
