-- DNC filtering (contact-engine part 2, docs/contact-engine/02-dnc-filtering.md §4, §10;
-- 🔴-approved 2026-09-30 at revision 18).
--
-- One record of "don't call me again", keyed by phone. dnc_numbers holds whether a phone
-- is blocked; dnc_log holds every block and lift. Every path that blocks turns the row on:
-- the verbs in service/dnc.py (kinds 'rep', 'admin'), door A applying a voice tombstone
-- ('intake'), a trigger on events for any qualifying event from any writer ('event'),
-- and the one-time backfill below ('backfill'). Only an admin's lift turns it off.
-- No foreign key on contact_id or event_id: the record outlives a hard delete, as a
-- tombstone does. dnc_runs records each completed daily scrub (status row 3).

create table dnc_runs (
  id          uuid primary key default gen_random_uuid(),
  started_at  timestamptz not null,
  limited     boolean not null
);
create index dnc_runs_unlimited_idx on dnc_runs (started_at) where not limited;

create table dnc_numbers (
  phone_e164  text primary key,
  blocked     boolean not null,
  updated_at  timestamptz not null
);

create table dnc_log (
  seq         bigint generated always as identity primary key,
  phone_e164  text not null,
  kind        text not null
                check (kind in ('rep', 'admin', 'event', 'intake', 'backfill', 'lift')),
  actor       text not null,
  rep_id      uuid references partners(id),
  contact_id  uuid,
  event_id    bigint,
  reason      text,
  at          timestamptz not null,
  check ((kind = 'rep') = (rep_id is not null)),
  check (kind not in ('rep', 'admin', 'lift') or btrim(reason) <> '')
);
create index dnc_log_phone_idx on dnc_log (phone_e164, seq);

-- to_e164 in SQL: digits only; eleven with a leading 1 lose it; ten become +1 and the ten.
create function dnc_normalize(raw text) returns text language sql immutable as $$
  select case when d ~ '^1[0-9]{10}$' then '+' || d
              when d ~ '^[0-9]{10}$'  then '+1' || d end
  from (select regexp_replace(coalesce(raw, ''), '[^0-9]', '', 'g') as d) x
$$;

-- A payload's carried phones: phone_e164 and phone, in text form; none from a non-object.
create function dnc_carried_phones(p jsonb) returns text[] language sql immutable as $$
  select case when jsonb_typeof(p) = 'object' then
    array_remove(array[dnc_normalize(p->>'phone_e164'), dnc_normalize(p->>'phone')], null)
  else '{}'::text[] end
$$;

-- A qualifying event. An absent reason or channel counts; a non-object payload reads as
-- absent, so a qualifying type on a contact still blocks that contact's phone.
create function dnc_qualifies(t text, p jsonb) returns boolean language sql immutable as $$
  select case t
    when 'contact.opt_out' then
      (case when jsonb_typeof(p) = 'object' then p->>'reason' end)
        is distinct from 'do_not_mail'
    when 'contact.suppressed' then
      coalesce((case when jsonb_typeof(p) = 'object' then p->>'channel' end), '')
        not in ('mail', 'sms')
    else false end
$$;

create function dnc_block(phone text, kind text, actor text, contact uuid, event bigint,
                          reason text, at timestamptz) returns void language sql as $$
  insert into dnc_numbers (phone_e164, blocked, updated_at) values (phone, true, now())
    on conflict (phone_e164) do update set blocked = true, updated_at = now();
  insert into dnc_log (phone_e164, kind, actor, contact_id, event_id, reason, at)
    values (phone, kind, actor, contact, event, reason, at);
$$;

-- Phones are locked in sorted order, so one event never deadlocks with itself.
create function dnc_block_from_event() returns trigger language plpgsql as $$
declare
  ph text;
begin
  if not dnc_qualifies(new.type, new.payload) then
    return null;
  end if;
  for ph in
    select distinct x
    from unnest(dnc_carried_phones(new.payload)
                || array(select phone_e164 from contacts
                         where id = new.contact_id and phone_e164 is not null)) as x
    order by x
  loop
    perform dnc_block(ph, 'event', 'system', new.contact_id, new.id, null, now());
  end loop;
  return null;
end
$$;

create trigger dnc_block_on_insert after insert on events
  for each row execute function dnc_block_from_event();

create trigger dnc_block_on_attach after update of contact_id on events
  for each row when (new.contact_id is distinct from old.contact_id)
  execute function dnc_block_from_event();

-- Every phone blocked any way before this migration: a flag; a voice tombstone by phone,
-- or by list key through the intake rows (each row's phone and its contact's phone); a
-- qualifying event (its contact's phone and its carried phones). Returns how many.
create function dnc_backfill() returns integer language plpgsql as $$
declare
  ph text;
  n  integer := 0;
begin
  for ph in
    select distinct p from (
      select phone_e164 as p from contacts where do_not_call
      union all
      select phone_e164 from suppression_tombstones where channel = 'voice'
      union all
      select i.phone_e164 from suppression_tombstones t
        join intake_cslb_ca i on i.list_key = t.list_key where t.channel = 'voice'
      union all
      select c.phone_e164 from suppression_tombstones t
        join intake_cslb_ca i on i.list_key = t.list_key
        join contacts c on c.id = i.contact_id where t.channel = 'voice'
      union all
      select i.phone_e164 from suppression_tombstones t
        join intake_fbn_ca i on i.list_key = t.list_key where t.channel = 'voice'
      union all
      select c.phone_e164 from suppression_tombstones t
        join intake_fbn_ca i on i.list_key = t.list_key
        join contacts c on c.id = i.contact_id where t.channel = 'voice'
      union all
      select c.phone_e164 from events e join contacts c on c.id = e.contact_id
        where e.type in ('contact.opt_out', 'contact.suppressed')
          and dnc_qualifies(e.type, e.payload)
      union all
      select unnest(dnc_carried_phones(e.payload)) from events e
        where e.type in ('contact.opt_out', 'contact.suppressed')
          and dnc_qualifies(e.type, e.payload)
    ) s
    where p is not null
    order by p
  loop
    perform dnc_block(ph, 'backfill', 'backfill', null, null, null, now());
    n := n + 1;
  end loop;
  return n;
end
$$;

select dnc_backfill();

grant select on dnc_runs, dnc_numbers, dnc_log to me_user_ro;
