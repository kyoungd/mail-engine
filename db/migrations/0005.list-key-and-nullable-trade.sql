-- List-source generalization. The spine takes any purchased list through an intake
-- adapter (intake/), so two CSLB-shaped columns get their real meaning:
--   * cslb_license -> list_key: the per-list unique dedupe key, adapter-prefixed so
--     lists never collide ('cslb-123456', 'fbn-ca-2024023299').
--   * trade drops NOT NULL: an FBN filer's trade is genuinely unknown. "No trade =
--     invalid row" was a CSLB data-quality rule and moves into that list's adapter;
--     the universal rule (enforced in load_list) is that a row must be targetable —
--     trade or segment.

alter table contacts rename column cslb_license to list_key;
alter table contacts alter column trade drop not null;
