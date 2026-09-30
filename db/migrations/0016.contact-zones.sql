-- Time zone (contact-engine part 3, docs/contact-engine/03-time-zone.md §4.3, §10).
--
-- A zone the holding rep or an admin set for a contact, append-only; the row with the
-- highest seq replaces the zones the phone and state give. rep_id is null when an admin
-- set it. The rows are the log of zone changes.

create table contact_zones (
  seq         bigint generated always as identity primary key,
  contact_id  uuid not null references contacts(id) on delete cascade,
  zone        text not null check (zone in (
                'America/New_York', 'America/Chicago', 'America/Denver',
                'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage',
                'America/Adak', 'Pacific/Honolulu', 'America/Puerto_Rico',
                'Pacific/Guam', 'Pacific/Pago_Pago')),
  actor       text not null,
  rep_id      uuid references partners(id),
  at          timestamptz not null
);
create index contact_zones_contact_idx on contact_zones (contact_id, seq);

grant select on contact_zones to me_user_ro;
