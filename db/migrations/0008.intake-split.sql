-- Grain migration, Phase 1 (design ingest-contact-migration.md §2.1/§2.4, revision 7).
-- ADDITIVE ONLY. Nothing existing is dropped or altered here: every current code path
-- still reads contacts.list_key/trade/license_class exactly as before. The order-
-- dependent DDL that removes them — the pieces-constraint drop, the phone-unique index,
-- the contact column drops — deliberately lives in migrate_grain's in-script swap
-- (design §7), which lands with Phase 2 so the swap and the code surviving it cross one
-- boundary together (implementation plan, ground rule 4).
--
-- The contacts grain changes from CSLB *license record* to *business*: immutable
-- per-source intake tables hold the raw rows, and a slim contacts becomes phone-unique.
-- One table per adapter (FR-1 anticipates more states/sources); both v1 tables share
-- the canonical-CSV core, which gains `trades` in this change.

create table intake_cslb_ca (
  id             uuid primary key default gen_random_uuid(),
  list_key       text not null unique,            -- 'cslb-<license>'
  contact_id     uuid not null references contacts(id),
  business_name  text,
  contact_name   text,
  trade          text,                            -- primary trade (adapter first-match; feeds segment)
  trades         text[] not null default '{}',    -- ALL matching NMC trades for the row's classes
  license_class  text,                            -- 'C36' / 'C20|C36'
  phone_e164     text,                            -- normalized at load
  email          text,
  addr_line1     text,
  addr_line2     text,
  addr_city      text,
  addr_state     text,
  addr_zip       text,
  segment        text,
  do_not_mail    boolean not null default false,  -- canonical-CSV flag, preserved raw
  is_primary     boolean not null default false,  -- the winner row (§3): exactly one true per contact
  -- address standardization: written ONLY by the verify_addresses job (§5)
  std_addr_line1 text,
  std_addr_line2 text,
  std_addr_city  text,
  std_addr_state text,
  std_addr_zip   text,                            -- ZIP+4
  delivery_point text,                            -- stable per-mailbox identifier (USPS barcode)
  deliverability text,                            -- vendor verdict, verbatim; read by §6's undeliverable exclusion
  std_verified_at timestamptz,                    -- named apart from contacts.addr_validated_at on purpose (§5)
  ingested_at    timestamptz not null default now()
);
create index intake_cslb_ca_contact_idx on intake_cslb_ca (contact_id);
-- DB-enforces §3's exactly-one-primary-per-contact (inherit + dedupe both key on it;
-- corruption would misroute mail).
create unique index intake_cslb_ca_primary_key on intake_cslb_ca (contact_id)
  where is_primary;
create index intake_cslb_ca_phone_idx on intake_cslb_ca (phone_e164);
create index intake_cslb_ca_dp_idx    on intake_cslb_ca (delivery_point);

-- Same shape; list_key 'fbn-ca-<filing>'. phone_e164 is always null in practice —
-- FBN filings carry no phone at all, which is why they are mail-code-only for
-- attribution and one contact per filing rather than phone-merged.
create table intake_fbn_ca (
  id             uuid primary key default gen_random_uuid(),
  list_key       text not null unique,
  contact_id     uuid not null references contacts(id),
  business_name  text,
  contact_name   text,
  trade          text,
  trades         text[] not null default '{}',
  license_class  text,
  phone_e164     text,
  email          text,
  addr_line1     text,
  addr_line2     text,
  addr_city      text,
  addr_state     text,
  addr_zip       text,
  segment        text,
  do_not_mail    boolean not null default false,
  is_primary     boolean not null default false,
  std_addr_line1 text,
  std_addr_line2 text,
  std_addr_city  text,
  std_addr_state text,
  std_addr_zip   text,
  delivery_point text,
  deliverability text,
  std_verified_at timestamptz,
  ingested_at    timestamptz not null default now()
);
create index intake_fbn_ca_contact_idx on intake_fbn_ca (contact_id);
create unique index intake_fbn_ca_primary_key on intake_fbn_ca (contact_id)
  where is_primary;
create index intake_fbn_ca_phone_idx on intake_fbn_ca (phone_e164);
create index intake_fbn_ca_dp_idx    on intake_fbn_ca (delivery_point);

-- Permanent audit of the one-time merge (§2.4). Writer: the prod migration, once.
-- Readers: forensics and the restatement report. Never read by live logic.
create table contact_merge_map (
  old_contact_id uuid primary key,
  new_contact_id uuid not null,
  merged_at      timestamptz not null default now()
);

-- Seed contacts are identified by a stable key rather than by the address fields they
-- carry, so a founder address edit does not mint a second seed (§3's retire_seed and
-- the seed-exemption paths key on this).
alter table contacts add column seed_key text unique;

-- Phase 2 drops pieces' `unique (contact_id, wave_id)` — merged history makes that pair
-- ambiguous, and resume idempotency moves onto mailer_code (§2.3). The lookups that
-- constraint was incidentally serving need an index of their own once it goes; adding it
-- now keeps that a pure removal in Phase 2 rather than a swap.
create index pieces_contact_wave_idx on pieces (contact_id, wave_id);
