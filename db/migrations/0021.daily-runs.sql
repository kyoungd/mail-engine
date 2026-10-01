-- Running it (contact-engine part 6b, docs/contact-engine/06b-running-it.md §4.1, §10;
-- approved 2026-10-01 at revision 8).
--
-- One row per nightly that completes; the status read's `daily_run_missing` reads the
-- newest.

create table daily_runs (
  id           bigint generated always as identity primary key,
  finished_at  timestamptz not null
);
create index daily_runs_finished_idx on daily_runs (finished_at);

grant select on daily_runs to me_user_ro;
