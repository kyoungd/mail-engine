-- The sale and the 90 days (contact-engine part 5c,
-- docs/contact-engine/05c-sale-and-90-days.md §4.1, §10; approved 2026-09-30 at
-- revision 7).
--
-- The seller of a website sale, written once by the nightly's won step: the rep who
-- held the contact when the nightly first saw the sale, or the house. No foreign key:
-- partners are never deleted in production, and the frozen test helper `_rm_partner`
-- deletes partners while their contacts keep their state rows.

alter table contact_state add column web_seller uuid;
