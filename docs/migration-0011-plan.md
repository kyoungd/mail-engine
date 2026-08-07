# Migration `0011` plan — partner-sourced attribution

*🔴 plan, revision 3, 2026-08-06. Implements the schema half of
`partner-sourced-leads.md` rev 5. NOT YET APPROVED — nothing has been applied.*

**Revision 3** adds `contacts.permission_at` for the operator's 90-day
personal-list rule (a number in a partner's personal list is on their sheet for
90 days with no FTC-registry check; after that ordinary rules resume). It is
written by the import and read by the export in the same batch, so it does not
repeat rev 1's writerless-column defect.

**Revision 2 shrank this to one column.** Rev 1 also added
`partners.deactivated_at`, which review rejected on three counts: it is stored
state with **no reset path** (a partner deactivated → reactivated → deactivated
again keeps the stale timestamp, so the release step fires immediately and
destroys attribution with zero reversal window — the exact defect this design
rejected `custody_kind` for); it has **no writer** in this change or the
follow-up list; and it belongs with the nightly release step that reads it. It
moves to that batch, where writer, reader, and a clear-on-reactivate rule land
together.

## The DDL, as it would be written — `db/migrations/0011.sourced-attribution.sql`

```sql
-- Partner-sourced numbers (partner-sourced-leads.md rev 4, decided 2026-08-06).
--
-- Attribution, not status: this records WHO sourced a contact, so custody kind
-- is DERIVED (sourced_by_partner_id = owner_id ⇒ sourced: uncounted,
-- unexpiring) rather than stored. A stored kind would need a reset path on
-- every return-to-house — won, suppressed, DNC-hit, reclaimed — and a stranded
-- value would make a later ISSUED assignment never expire. Persistence is the
-- intent here, so that bug cannot exist. Persistence is also what implements
-- "never reassigned to another partner": the assignment audience excludes
-- contacts attributed elsewhere, so a released contact returns to its sourcer.
--
-- Written by the referral import; cleared only by an explicit operator act (and
-- by the nightly release step, when that lands with partners.deactivated_at).

alter table contacts add column sourced_by_partner_id uuid references partners(id);

-- The permission date from the import CSV, and the clock for the 90-day
-- personal-list window (operator rule, 2026-08-06: a number in the partner's
-- personal list is on their sheet for 90 days without an FTC-registry check;
-- after that it falls back to ordinary rules). Dated from when permission was
-- GIVEN, not when it was imported, because that is when the legal window opens.
-- Read by the export, which applies the registry predicates only to rows
-- outside this window. Our own do_not_call and tombstone checks are never
-- waived by it.
alter table contacts add column permission_at date;
```

That is the whole migration. Both columns are written by the import verb and
read by the export, in the same batch — neither ships without a writer.

## Choices made

- **Plain FK, no `ON DELETE` clause.** Rev 1 proposed `on delete set null`;
  dropped. It would be the schema's **first and only** `ON DELETE` action (no
  migration in `db/migrations/` contains one), it is an *automatic* clear in a
  design whose rule is "cleared only by an explicit operator act", and its
  stated justification was wrong: deleting a partner who holds contacts is
  already blocked by `contacts_owner_id_fkey` (NO ACTION), so the production
  scenario it was defending against cannot occur. NO ACTION additionally forces
  the right order — clear attribution, then delete the partner.
  **Known consequence:** two test sites delete partners without pre-clearing
  contact references (`tests/acceptance/test_partner_custody.py:348,362` and
  `tests/e2e/test_partner_journey.py:95`). They are safe today because nothing
  writes the column yet, and must pre-clear once the import verb exists.
- **No index.** Rev 1 proposed a partial index justified by three readers; one
  of them (the audience exclusion, `sourced_by is null or = :pid`) cannot use a
  `where … is not null` partial index at all, and the assignment audience
  already full-scans every non-seed contact `for update`. The other two readers
  do not exist yet, and `contacts.owner_id` has no index today either. Add it
  with the release step, if measurement says so.
- **Bare `add column`**, matching `0007`/`0009`/`0010`; `0003`/`0004` use
  `if not exists`, so both conventions exist and the newer one is followed.

## Deliberately NOT in this migration

- **The taxonomy addition.** Rev 1 was ambiguous — the parent design assigned
  `contact.permission_recorded` to migration 0011, while the plan's own
  verification argued nothing new lands here. Settled: it is a one-line Python
  change (`domain/taxonomy.py`; `events.type` is plain `text not null` at
  `0001.create-schema.sql:97`, so no DDL) and it lands **with the import verb**,
  which is the first thing that emits it. The parent doc §5 is corrected to match.
- **`partners.deactivated_at`** — moved, see the header note.
- No data migration, no backfill (`sourced_by_partner_id` is meaningfully NULL
  for all 100,444 contacts), no drops, no table rewrite, no new tables, no enum
  change, no grant work (`0002` grants `select` at **table** level, which covers
  columns added later — verified empirically: `me_user_ro` can already read
  `do_not_call`, added by `0010` long after `0002`).

## Applying it

- `make migrate` chains `yoyo apply` **and then** `migrate_grain
  --ensure-swapped`. On an already-swapped database the second step is a no-op;
  on a populated *pre-swap* database it halts — after yoyo has committed. Both
  checkouts are post-swap, so this is a note, not a hazard.
- `alter table contacts` takes `ACCESS EXCLUSIVE` briefly. Work is sub-second
  (metadata-only column add; FK validation against an all-NULL column is
  trivial), but `service/assignment.py:252-257` holds `for update` row locks
  across every non-seed contact for the length of an assign. **Do not apply
  during an assign or the nightly.**
- **Reversal is `alter table contacts drop column sourced_by_partner_id`** —
  and note that a manual drop leaves the `_yoyo_migration` row in place, so a
  later `make migrate` will NOT re-apply 0011; delete that row too. Dropping
  after the import verb ships would discard recorded attribution.

## Verification after apply

1. `contacts` still 100,444; `sourced_by_partner_id` 100% NULL.
2. The FK exists and is NO ACTION:
   `select confdeltype from pg_constraint where conname =
   'contacts_sourced_by_partner_id_fkey'` → `a`.
3. Full suite green — **518 collected / 2 deselected** — plus ruff and pyright.
   Nothing reads the column yet, so a green suite is the proof it is inert.
4. `me_user_ro` can select the new column.

Note that `test_migrations_idempotent.py` is **not** evidence about this DDL:
yoyo records applied migrations, so a second pass never re-executes 0011. Its
own docstring calls it proof of idempotent *tooling*.

## Follows separately (🟡, each with its own test gate)

Import verb (+ the taxonomy line) · **won-termination predicate fix — must ship
in the SAME batch, since a sourced contact who becomes a customer would
otherwise stay on the partner's sheet (S-10's worst case)** · export LEFT-join +
`origin` column · reclaim restriction · audience exclusion · holdings split
(`partners_cli` and `partner_report` count differently today) · nightly release
step **with `partners.deactivated_at`, its `partners_cli` writer, and
clear-on-reactivate** · console item.
