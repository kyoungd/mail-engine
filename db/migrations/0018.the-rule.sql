-- The rule (contact-engine part 5b, docs/contact-engine/05b-the-rule.md §4.1, §4.2,
-- §10; approved 2026-09-30 at revision 6).
--
-- rep_settings holds a rep's four settings (no row: the defaults). contact_state holds
-- where each contact stands, written by the act that changes it under the contact's
-- lock; dates are worked out on read. Closings by outcome are read from calls.

create table rep_settings (
  rep_id         uuid primary key references partners(id),
  voicemails     smallint not null check (voicemails in (1, 2, 3)),
  calls          smallint not null check (calls in (3, 5, 8)),
  days_between   smallint not null check (days_between in (3, 5, 7)),
  rest_months    smallint not null check (rest_months in (1, 3, 6)),
  updated_at     timestamptz not null
);

create table contact_state (
  contact_id      uuid primary key references contacts(id),
  list            text not null default 'sequence'
                    check (list in ('sequence', 'got_callback', 'follow_up')),
  rep_closed      boolean not null default false,
  calls           integer not null default 0 check (calls >= 0),
  voicemails      integer not null default 0 check (voicemails between 0 and calls),
  last_call_at    timestamptz,
  last_call_busy  boolean not null default false,
  pause_until     date,
  updated_at      timestamptz not null,
  check ((calls = 0) = (last_call_at is null)),
  check (last_call_at is not null or not last_call_busy)
);

create index calls_closings_idx on calls (contact_id)
  where outcome in ('signed_up', 'wrong_number', 'not_interested');

grant select on rep_settings, contact_state to me_user_ro;
