-- Vouching (contact-engine part 7, docs/contact-engine/07-vouching.md §4, §10;
-- 🔴-approved 2026-10-02 at revision 2, and the gate test with no foreign key on rep_id).
--
-- vouches holds every vouch a rep made for a contact, from the vouch verb ('rep') or
-- door B ('intake'); vouch_withdrawals holds each withdrawal of one. Both append-only,
-- written only by service/vouch.py. custody_mark is the id of the contact's latest
-- custody event when the vouch was made: the vouch stops counting once a later custody
-- event takes the contact from its rep. A call opened under a vouch records it; such a
-- call may lack dnc_checked_at.
-- No foreign key on rep_id: partners are never deleted in production, and frozen test
-- fixtures delete their reps after door B has vouched (as 0019's web_seller).

create table vouches (
  id             uuid primary key default gen_random_uuid(),
  seq            bigint generated always as identity unique,
  contact_id     uuid not null references contacts(id),
  rep_id         uuid not null,
  phone_e164     text not null check (phone_e164 ~ '^\+1[0-9]{10}$'),
  reason         text not null check (reason in ('met_in_person', 'they_contacted_me')),
  confirmation   text not null check (btrim(confirmation) <> ''),
  source         text not null check (source in ('rep', 'intake')),
  custody_mark   bigint not null,
  at             timestamptz not null
);
create index vouches_contact_rep_idx on vouches (contact_id, rep_id, seq);

create table vouch_withdrawals (
  id        uuid primary key default gen_random_uuid(),
  vouch_id  uuid not null unique references vouches(id),
  reason    text not null check (btrim(reason) <> ''),
  at        timestamptz not null
);

alter table calls add column vouch_id uuid references vouches(id);
alter table calls add column vouched_status text check (vouched_status in
  ('not_checked', 'not_covered', 'on_dnc_file', 'check_too_old'));
alter table calls add constraint calls_vouch_status_check
  check ((vouch_id is null) = (vouched_status is null));
alter table calls add constraint calls_vouch_opened_check
  check (vouch_id is null or opened_at is not null);
alter table calls drop constraint calls_check3;
alter table calls add constraint calls_opened_basis_check check (opened_at is null or (
  (dnc_checked_at is not null or vouch_id is not null)
  and inside is not null and zones is not null and cardinality(zones) > 0
  and (inside or outside_confirmed)));

grant select on vouches, vouch_withdrawals to me_user_ro;
