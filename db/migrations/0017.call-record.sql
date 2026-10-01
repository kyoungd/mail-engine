-- The call record (contact-engine part 5a, docs/contact-engine/05a-call-record.md §4.8,
-- §10; approved 2026-09-30 at revision 5).
--
-- calls holds one row per call a rep opened, and one per outcome recorded from the card
-- (no opened_at). An outcome is set once; `happened` says whether a call happened (7.8).
-- memos and calls_received complete the record. Nothing is deleted (8.8).

create table calls (
  id                 uuid primary key default gen_random_uuid(),
  contact_id         uuid not null references contacts(id),
  rep_id             uuid not null references partners(id),
  phone_e164         text check (phone_e164 ~ '^\+1[0-9]{10}$'),
  opened_at          timestamptz,
  dnc_checked_at     timestamptz,
  dnc_snapshot_id    uuid references dnc_snapshots(id),
  zones              text[],
  inside             boolean,
  outside_confirmed  boolean not null default false,
  outcome            text check (outcome in ('no_answer', 'left_voicemail',
                       'owner_unavailable', 'busy', 'call_not_placed', 'spoke',
                       'follow_up', 'not_interested', 'wrong_number', 'signed_up')),
  outcome_at         timestamptz,
  cleared_by         text,
  cleared_reason     text,
  cleared_at         timestamptz,
  undone_reason      text,
  undone_at          timestamptz,
  happened           boolean generated always as (
                       opened_at is not null and outcome is not null
                       and outcome <> 'call_not_placed') stored,
  -- a call opened, or an outcome from the card
  check ((opened_at is null) = (phone_e164 is null)),
  check (opened_at is not null or outcome is not null),
  check (opened_at is not null or outcome not in ('no_answer', 'left_voicemail',
         'owner_unavailable', 'busy', 'call_not_placed')),
  -- an opened call relied on a check, and on the hours or a confirmation
  check (opened_at is null or (dnc_checked_at is not null and inside is not null
         and zones is not null and cardinality(zones) > 0
         and (inside or outside_confirmed))),
  check (opened_at is not null or (dnc_checked_at is null and dnc_snapshot_id is null
         and zones is null and inside is null and not outside_confirmed)),
  check (not outside_confirmed or inside is false),
  check ((outcome is null) = (outcome_at is null)),
  check (outcome_at is null or opened_at is null or outcome_at >= opened_at),
  check ((cleared_at is null) = (cleared_by is null)),
  check ((cleared_at is null) = (cleared_reason is null)),
  check (cleared_at is null or (btrim(cleared_reason) <> '' and btrim(cleared_by) <> ''
         and outcome is null and opened_at is not null and cleared_at >= opened_at)),
  check ((undone_at is null) = (undone_reason is null)),
  check (undone_at is null or (btrim(undone_reason) <> ''
         and outcome is not null and outcome in ('signed_up', 'wrong_number')
         and undone_at >= outcome_at))
);
create unique index calls_one_open_per_contact on calls (contact_id)
  where opened_at is not null and outcome is null and cleared_at is null;

create table memos (
  id          uuid primary key default gen_random_uuid(),
  contact_id  uuid not null references contacts(id),
  rep_id      uuid not null references partners(id),
  call_id     uuid references calls(id),
  text        text not null check (btrim(text) <> ''),
  at          timestamptz not null
);
create index memos_contact_idx on memos (contact_id, at);

create table calls_received (
  id           uuid primary key default gen_random_uuid(),
  contact_id   uuid not null references contacts(id),
  rep_id       uuid not null references partners(id),
  phone_e164   text not null check (phone_e164 ~ '^\+1[0-9]{10}$'),
  received_at  timestamptz not null,
  resolution   text check (resolution in ('spoke', 'call_back', 'dismiss')),
  resolved_at  timestamptz,
  check ((resolution is null) = (resolved_at is null)),
  check (resolved_at is null or resolved_at >= received_at)
);
create index calls_received_rep_idx on calls_received (rep_id, received_at);

grant select on calls, memos, calls_received to me_user_ro;
