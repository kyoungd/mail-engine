-- Partner custody foundation (partner-lead-assignment.md revision 7, Phase 1).
-- partners (incl. the four R1 report/feed columns riding here per
-- partner-report-implementation.md R1), assignment_batches, feed_watermarks,
-- contacts.owner text -> owner_id uuid FK, and the assigned-phone exclusivity index.
--
-- The house row's identity is PINNED, not discovered: the uuid below must equal
-- config/params.py HOUSE_PARTNER_ID. Every return-to-house set_owner call targets it,
-- the genesis rule resolves to it, and _resolve_recipient's YOUNG branch returns it.
--
-- Note: jobs/migrate_grain.py's MERGE preflight reads contacts.owner and will now
-- fail loudly (SQL error) if the one-shot historical merge is ever re-run — correct:
-- post-0009 a merge needs an owner rule first (the preflight's own message says so).

create table partners (
  id              uuid primary key default gen_random_uuid(),
  name            text not null unique,
  status          text not null default 'active' check (status in ('active', 'inactive')),
  channel         text check (channel in ('email', 'sms')),
  channel_address text,
  base_addr_line1 text,
  base_addr_city  text,
  base_addr_state text,
  base_addr_zip   text,
  radius_miles    integer,
  weekly_hours    integer,
  -- R1 report/feed columns (partner-report-implementation.md R1)
  sales_rep_id    bigint,
  partner_code    text unique,
  last_report_at  timestamptz,
  last_export_at  timestamptz,
  created_at      timestamptz not null default now()
);

insert into partners (id, name, status, channel, channel_address)
values ('00000000-0000-4000-8000-000000000001', 'Young', 'active', 'email', 'young@nevermisscall.com')
on conflict (id) do nothing;

insert into partners (name, status)
values ('John', 'active')
on conflict (name) do nothing;

create table assignment_batches (
  id              uuid primary key default gen_random_uuid(),
  partner_id      uuid not null references partners(id),
  idempotency_key text not null unique,
  requested_count integer,
  delivered_count integer,
  expires_at      timestamptz,
  actor           text not null,
  -- the request verbatim (rule or id-list) for the retry receipt, plus its hash
  -- for the key-mismatch check (S-1)
  request         jsonb,
  request_hash    text,
  created_at      timestamptz not null default now()
);

-- owner text -> owner_id FK. Every existing row is 'young' (verified: the column
-- never had a writer), so the not-null default IS the backfill. The default is
-- load-bearing (revision 5): load_list and ensure_seed_contacts INSERT without any
-- owner column and must keep working.
alter table contacts add column owner_id uuid not null
  default '00000000-0000-4000-8000-000000000001' references partners(id);
alter table contacts drop column if exists owner;

alter table contacts add column assignment_batch_id uuid references assignment_batches(id);

-- One assigned row per phone, enforced by storage. Since the grain merge the
-- contacts table is already one non-seed row per phone (contacts_phone_unique),
-- so this is belt-and-suspenders, no longer the load-bearing twin guard
-- (revision 7).
create unique index contacts_assigned_phone_unique on contacts (phone_e164)
  where assignment_batch_id is not null;

-- Per-feed watermark rows (nmc-close-feed-contract.md §2/§8). Created here; first
-- written by the close feed's sync (partner-report-implementation.md R3) — until
-- then it has no writer, named honestly; its reader applies
-- since = min(stored_watermark, now - 45d), so an unwritten row is not a
-- correctness hazard.
create table feed_watermarks (
  feed_name  text primary key,
  watermark  timestamptz not null,
  updated_at timestamptz not null default now()
);
