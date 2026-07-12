-- Cancel-and-redraft is the correction loop for anything past draft, so a cancelled
-- wave must not hold its name forever. Uniqueness that matters is among live waves:
-- the plain unique constraint becomes a partial index excluding status='cancelled'.

alter table waves drop constraint waves_name_key;
create unique index waves_name_active_key on waves (name) where status <> 'cancelled';
