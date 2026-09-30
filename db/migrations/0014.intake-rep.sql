-- A rep's numbers (contact-engine part 1, docs/contact-engine/01-intake.md §4.4, §10;
-- 🔴-approved 2026-09-29/30, answers 6, 10, 13).
--
-- Immutable, like intake_cslb_ca and intake_fbn_ca: what the rep entered, the rep,
-- how they got the number, and the confirmation they gave (decision 3.2). Written
-- only by service/rep_intake.add_numbers. Whose a contact is follows from its
-- primary intake row: a contact whose primary row is here is that rep's own.
--
-- No list_key (a rep's rows have no list to dedupe against), no mail-address or
-- delivery columns, and added_at has no default: it is always the time handed in.
-- No cascade on contact_id, like the other intake tables.
create table intake_rep (
  id             uuid primary key default gen_random_uuid(),
  contact_id     uuid not null references contacts(id),
  is_primary     boolean not null default false,
  rep_id         uuid not null references partners(id),
  phone_e164     text not null
                   check (phone_e164 ~ '^\+1[2-9][0-9]{2}[2-9][0-9]{6}$'),
  business_name  text,
  contact_name   text,
  contact_role   text,
  trade          text,
  addr_city      text,
  addr_state     text,
  how_obtained   text not null check (how_obtained in
                   ('met_in_person', 'they_contacted_me', 'referral', 'public_or_research')),
  confirmation   text not null check (btrim(confirmation) <> ''),
  added_at       timestamptz not null
);

create index intake_rep_contact_idx on intake_rep (contact_id);
create unique index intake_rep_primary_key on intake_rep (contact_id) where is_primary;
