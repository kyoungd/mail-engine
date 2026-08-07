-- Back out migration 0011 — the partner-sourced-numbers feature is DEFERRED
-- (operator decision 2026-08-06; see docs/partner-sourced-leads.md header).
--
-- Why a down-migration rather than leaving two unused nullable columns: 0011's
-- readers are all being removed in the same change (the export's personal-window
-- waiver, the assignment audience's attribution gate, the holdings splits). A
-- column read by nothing is harmless; a column that a FUTURE reader might find
-- and trust — populated by nothing — is TD-2 exactly, the dead-writer class this
-- repo already carries as debt. Dropping is the honest state: the feature is not
-- half-built, it is not built.
--
-- Production never received 0011 (mailengine_prod stops at 0010), so this is a
-- dev-only correction. Re-applying 0011 verbatim is the way back if the feature
-- is revived; nothing here is destructive of data that ever existed — both
-- columns were written only by service/referrals.py, which never ran against a
-- real import.
alter table contacts drop column if exists sourced_by_partner_id;
alter table contacts drop column if exists permission_at;
