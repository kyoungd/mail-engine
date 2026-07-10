-- Drift baseline. approve_wave records the audience size it approved so that
-- execute_wave can halt when the audience resolved at drop time has drifted beyond
-- tolerance (a few contacts suppressed between approve and drop is fine; a large
-- swing means the wave should be re-reviewed, not fired).

alter table waves add column if not exists approved_audience_count int;
