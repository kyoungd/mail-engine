-- Mail Engine schema (Postgres 15+)
-- Transcribed verbatim from direct-mail-ai-data.md §2. Do not edit to "fix"
-- a discrepancy; a schema change is an escalation trigger (see implementation plan).

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
  cslb_license      text unique,
  business_name     text,
  contact_name      text,
  trade             text not null,
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
