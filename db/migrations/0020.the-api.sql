-- The API (contact-engine part 6a, docs/contact-engine/06a-the-api.md §4.3, §4.4, §10;
-- approved 2026-10-01 at revision 6).
--
-- A rep on the website's roster is one partner. api_requests remembers each action's
-- answer for (caller, who, key), written in the act's own transaction.

alter table partners add constraint partners_sales_rep_id_unique unique (sales_rep_id);

create table api_requests (
  caller       text not null check (caller in ('dialer', 'website')),
  who          text not null,
  key          text not null check (btrim(key) <> '' and length(key) <= 200),
  method       text not null,
  path         text not null,
  body_hash    text not null,
  status       integer not null,
  answer       text not null,
  at           timestamptz not null,
  primary key (caller, who, key)
);

grant select on api_requests to me_user_ro;
