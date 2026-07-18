-- Seed pieces (PRD FR-4): a founder-address contact flagged is_seed rides every wave
-- as one extra piece, so each drop lands a physical sample in the founder's hands (the
-- only check on production print quality; IMb tracking already covers delivery timing).
-- Excluded from all response metrics (FR-7/FR-13): a seed never responds, so counting
-- it would deflate the response rate. Additive; existing rows default false.

alter table contacts add column is_seed boolean not null default false;

-- The audience resolver appends every seed to every wave; this keeps that lookup cheap.
create index contacts_seed_idx on contacts (id) where is_seed;
