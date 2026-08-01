-- Suppression split + DNC scrub (partner-lead-assignment.md S-6/S-9, Phase 2,
-- 🔴-approved 2026-08-01).
--
-- Per-channel suppression columns: the one contact-level "suppressed" verdict
-- cannot answer *suppressed from what?* — do_not_call must not stop postcards,
-- and a bounced postcard must not strand a good phone number. dnc_registry is
-- deliberately OUTSIDE the do_not_* family: it records what the registry said,
-- not what a person asked for, so a later scrub may clear it (S-6).
--
-- The tombstone survives FR-8's CCPA hard-delete (itself unbuilt): written by
-- suppress() in the same transaction as flag + event, consulted by load_list at
-- intake (by list_key AND phone) and by the Phase 4 assignment/export gates (by
-- phone). Write-at-suppress-time, not delete-time.

alter table contacts add column do_not_call boolean not null default false;
alter table contacts add column dnc_registry boolean not null default false;
alter table contacts add column dnc_checked_at timestamptz;
alter table contacts add column address_undeliverable boolean not null default false;

-- Org-level registry subscriptions (design §6: the subscription — not the
-- assignment — bounds the scrub). Writer: jobs/subscribe_area_codes.
create table dnc_subscriptions (
  area_code     text primary key,
  subscribed_at timestamptz not null
);

-- Suppression tombstones (S-6, revisions 4-5). Either key may be null: an
-- all-channel opt_out writes one row per blocked channel.
create table suppression_tombstones (
  id         uuid primary key default gen_random_uuid(),
  phone_e164 text,
  list_key   text,
  channel    text not null check (channel in ('mail', 'sms', 'voice')),
  reason     text not null,
  created_at timestamptz not null default now()
);

create index suppression_tombstones_phone_idx on suppression_tombstones (phone_e164)
  where phone_e164 is not null;
create index suppression_tombstones_list_key_idx on suppression_tombstones (list_key)
  where list_key is not null;

-- The scrub sweeps stale checks in subscribed area codes (21-day cycle).
create index contacts_dnc_checked_idx on contacts (dnc_checked_at)
  where phone_e164 is not null and is_seed = false;
