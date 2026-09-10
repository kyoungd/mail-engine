-- Partner-supplied DNC snapshots (Architecture B, operator-decided 2026-09-09).
-- Schema only: no verbs, no readers, no client, no Worker — those are Phases 2-5.
--
-- The model: a partner downloads the FTC full list under their OWN SAN on their
-- own machine, a Cloudflare Worker takes the upload (token -> partner, key derived
-- server-side) into R2, and a pull job validates and records it here. NMC keeps its
-- own SAN and its five codes (operator Q3); not every partner will supply files
-- (Q4), so an area code may be covered by NMC, by a partner, by both, or by nobody.
--
-- NMC's own SAN is modeled as the HOUSE partner row, so "who holds the SAN" has one
-- type everywhere instead of a 'nmc' | <uuid> union — the same way contacts.owner_id
-- already models NMC-as-a-party. The default IS the backfill for the existing
-- subscription rows.
--
-- WARNING: nothing writes these columns until Phase 4. That is TD-2's shape (0012's
-- header: "a column that a FUTURE reader might find and trust — populated by
-- nothing"), so this migration is DEV-ONLY until the writers land; if the build
-- stalls, the honest state is a down-migration, not a half-populated schema.

-- 1. Subscriptions gain a holder. One code can now be covered twice.
alter table dnc_subscriptions add column san_holder_id uuid not null
  default '00000000-0000-4000-8000-000000000001' references partners(id);

alter table dnc_subscriptions drop constraint dnc_subscriptions_pkey;
alter table dnc_subscriptions add primary key (area_code, san_holder_id);

-- 2. The partner's FTC identity + the API token the Worker authenticates.
--    The token is stored hashed: it ships inside a binary on a rep's laptop and
--    is assumed to leak. Its only capability is posting a snapshot for its own
--    partner — no reads, no contact data, no other route.
alter table partners add column san_number           text;
alter table partners add column api_token_hash       text;
alter table partners add column api_token_issued_at  timestamptz;
alter table partners add column api_token_revoked_at timestamptz;

create unique index partners_api_token_hash_unique on partners (api_token_hash)
  where api_token_hash is not null;

-- 3. One row per uploaded snapshot, accepted or rejected. A rejection is evidence
--    too — "we received this file and refused it, here is why" is what answers a
--    later question about why a number went unscrubbed.
--
--    Uniqueness is PER HOLDER, not global: two subscribers pulling the same area
--    code on the same day may receive byte-identical content, so a global sha256
--    constraint would reject an honest upload as a duplicate. The relabeling case
--    the check defends against happens within one holder.
--    Identity (area_code, version_date, file_guid) is parsed from the FTC's own
--    filename, so a file whose NAME is not the portal's shape has none to record.
--    Those three are therefore nullable, with the guarantee moved to a
--    status-conditional check: an ACCEPTED snapshot is always fully identified.
create table dnc_snapshots (
  id                 uuid primary key default gen_random_uuid(),
  area_code          text,
  san_holder_id      uuid not null references partners(id),
  version_date       date,                   -- the FTC's own file date, from the filename
  file_guid          text,                   -- the FTC's per-generation guid
  sha256             text not null,
  object_key         text not null,          -- the R2 object
  line_count         integer,
  claimed_fetched_at timestamptz,            -- the partner's attestation
  uploaded_at        timestamptz not null,   -- when it landed in R2
  recorded_at        timestamptz not null default now(),
  recorded_by        text,                   -- actor, per the assignment_batches convention
  status             text not null check (status in ('accepted', 'rejected')),
  reject_reason      text,
  -- retention: keyed to USE, not age. The scrub sets checks_written; a snapshot
  -- that backed no verdict is evidence of nothing and its bytes go at 90 days
  -- (unless it is the newest for its code+holder). The ROW never goes.
  -- object_deleted_at keeps an audit query honest instead of letting it hit a
  -- mystery 404.
  checks_written     integer not null default 0,
  object_deleted_at  timestamptz,
  constraint dnc_snapshots_accepted_is_identified check (
    status <> 'accepted'
    or (area_code is not null and version_date is not null and file_guid is not null)
  )
);

-- Identity is unique among ACCEPTED snapshots only. A rejected row deliberately
-- repeats the identity it was refused for — a relabelled re-upload records the
-- SAME (holder, guid) as the accepted original, and that repetition IS the
-- evidence of the relabel. An unconditional constraint would refuse to store it.
create unique index dnc_snapshots_holder_guid_accepted
  on dnc_snapshots (san_holder_id, file_guid) where status = 'accepted';
create unique index dnc_snapshots_holder_sha_accepted
  on dnc_snapshots (san_holder_id, sha256) where status = 'accepted';

create index dnc_snapshots_resolution_idx
  on dnc_snapshots (area_code, version_date desc)
  where status = 'accepted';

-- 4. The verdict -> file link. Today a check records only a date string
--    (jobs/dnc_refresh.py: {"registry_version": version}), which under hybrid
--    identifies nothing and collides: append_event is ON CONFLICT DO NOTHING, so
--    two holders' same-dated snapshots for one code would silently drop the second
--    scrub's event while still writing the verdict. Phase 4 keys the external_id on
--    the snapshot id; this column is the O(1) answer to "which file cleared this
--    number" without walking the event stream.
alter table contacts add column dnc_snapshot_id uuid references dnc_snapshots(id);
