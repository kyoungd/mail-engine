-- Deal ownership. The judgment job routes each contact-level nudge to the founder
-- who owns the contact (DEAL_OWNER); YOUNG-recipient rules always go to Young.
-- Every contact today is CSLB-sourced (the mail channel Young owns), so the default
-- covers all current rows; affiliate-referred contacts get 'partner' at intake.

alter table contacts add column if not exists owner text not null default 'young';
