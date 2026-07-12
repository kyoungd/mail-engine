-- Read-only role grants (the analysis bypass). The role itself is created at
-- cluster init by db/init/00-roles.sh; here it gets SELECT and nothing else.
-- Role name is fixed to match READONLY_USER in .env.

grant usage on schema public to me_user_ro;
grant select on all tables in schema public to me_user_ro;
alter default privileges in schema public grant select on tables to me_user_ro;
