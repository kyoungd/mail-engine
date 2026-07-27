# Current state — 2026-07-27: grain design APPROVED (rev 7), implementation plan written, Phase 0 complete; nothing committed, no code changed

**This session** took the grain pivot from decision record to **approved,
buildable spec**: answered the five open questions (operator-decided),
wrote **`ingest-contact-migration.md`**, hardened it through **six independent
fresh-context reviews** (findings 12 → 10 → 11 → 6 → 7 → 6; gating 5 → 5 → 1 →
3 → 2 → 1; round 6's verdict was "fix one, patch two, approve" — applied as
revision 7), got 🔴 **operator approval**, wrote
**`ingest-contact-migration-implementation.md`** (phases 0–5), and executed
**Phase 0** (no code): Lob AV facts verified and recorded in design §5,
decisions.md entries written, PRD FR-1/FR-4 amended, TD-2 prevention note
added, partner migrations renumbered 0009/0010. All uncommitted working-tree
edits. A reusable **fresh-context doc reviewer subagent** now lives at
`../../../.claude/agents/doc-reviewer.md` (spawn blank, docs only, verify-only
reads; invoke via general-purpose + "adopt doc-reviewer.md" prompt — the
custom type isn't auto-registered).

## Where we are

Software state unchanged since 2026-07-18: gates green (279 offline + 1 e2e),
migrations 0001–0007 applied, prod pulled `c99033d`. Design truth:

- **`ingest-contact-migration.md` (rev 7) — APPROVED 2026-07-27.** One row per
  business; CSLB same phone ⇒ same contact; FBN per filing; intake tables
  (`intake_cslb_ca`/`intake_fbn_ca`, immutable, `is_primary`, `trades[]`,
  `do_not_mail`) + phone-unique `contacts`; address standardization at ingest
  (Lob AV, snapshot on intake rows, `std_verified_at`), delivery-point dedupe
  + undeliverable-only exclusion at audience resolution (exclusion BEFORE
  dedupe); pick rule = max-frequency-address candidate set → lowest
  `list_key`; next-action earliest-wins merge; `retire_seed` suppresses
  atomically; `SOURCE_REGISTRY` fails loud; stop-the-world cutover
  (`0008` → `migrate_grain --execute` → new code); dry-run =
  run-and-rollback, report is the 🔴 gate before `--execute`. Approval
  ratified brand-merge, the one-time readout restatement, and the pieces
  constraint relax.
- **`ingest-contact-migration-implementation.md`** — phases: 0 facts/docs
  (DONE), 1 additive schema+adapters+seam 🟡, 2 spine verbs 🟡, 3
  audience/execution 🟡, 4 verify_addresses job 🟡, 5 prod merge 🔴. Key
  executor wrinkle (ground rule 4): fresh envs = migrations + `migrate_grain
  --execute` (swap DDL lives in the script, not a migration) — wire into
  `make migrate`/test setup in Phase 1 or post-Phase-2 tests fail.
- **Lob AV facts (verified 2026-07-27, in design §5):** verdict enum
  `deliverable`/`deliverable_{missing,incorrect,unnecessary}_unit`/
  `undeliverable` (only `undeliverable` excludes); `delivery_point_barcode` is
  the dedupe key; ~102k backfill ≈ **$920 one-time** (one Growth AV month
  $450 + overage $0.009), separate from the print plan (stays Developer).
  Confirm exact tier prices in dashboard at purchase.
- **`partner-lead-assignment.md` still rev 6 — do NOT build from it.**
  Revision 7 (twin-row stratum deletion) comes after the grain migration
  completes. Its impl plan's migrations renumbered 0009/0010 today.

## Next session

1. **Phase 1** (🟡): frozen tests first — migration `0008` (additive DDL incl.
   `is_primary` partial unique), adapters emit `trades`, `AddressVerifier`
   Protocol + Fake, ground-rule-4 wiring. Show the tests, get the nod, green.
2. Then phases 2–4 in order, one per session; Phase 5 (prod merge) is 🔴 with
   the dry-run report as the gate.
3. After Phase 5: partner rev 7, then the partner queue (radius script, Q6
   counsel, Q10).

## Environment (local dev)

- Local Postgres `mailengine_dev` on **localhost:5432**, roles `me_user` /
  `me_user_ro` (password in `.env`). No Docker. `make migrate` applies through
  **0007**. `make run` → **http://127.0.0.1:8001**; no dotenv loader — make
  targets source `.env`.
- ⚠️ **`make test` AND `make e2e` TRUNCATE `mailengine_dev`**. Dev DB holds a
  7-row remnant; re-ingest (idempotent): `../ingestion-app-1/cslb-all.csv` →
  `load_list(path, source='cslb-ca')`; regenerate via `uv run python -m
  intake.cslb_ca ../ingestion-app-1/MasterLicenseData.csv --classes C36 -o
  /tmp/cslb.csv`. FBN: `intake.fbn_ca --year 2026` (source `fbn-ca-2026`).
  Prod DB still holds the full 102,431.
- **Note for Phase 2+:** after the new `load_list` lands, the re-ingest above
  exercises the new resolve-then-insert path — expect merged counts, not
  102,431.

## Open / undecided (carryover)

- **Activation table has NO writer** (TD-2) — unchanged; grain migration
  preflight asserts it stays untouched.
- **Q6 counsel hour** (B2B exemption, cellular CSLB numbers, SAN
  seller-of-record) — gates John dialing, not code. **Q10** close-visibility —
  decided-in-shape, option open. Both queued behind the grain work.
- **Live Lob key rotation (TD-9)** — still advised, still pending.
- **Lob AV plan purchase** — needed before Phase 4's live verification and the
  Phase 5 backfill; dashboard-confirm prices then.

## Watch-outs (carryover)

- Lob has **no `postcard.delivered`** event: `processed_for_delivery` is the
  proxy; tracking fires in **live env only**.
- Proof PDFs render **asynchronously** — refresh the embed; the e2e polls for
  `%PDF`.
- `.env` address values must be quoted (spaces break `make run` sourcing).
- `config/seeds.json` holds a **real address** — gitignored, never commit it.
- FBN rows have **zero phones** — excluded from everything voice and from the
  phone-merge (one contact per filing stays).
- The six review rounds repeatedly found defects **in the newest patch text**
  — when editing the design doc, re-review the paragraph you just wrote
  against its own §11.2 rule before moving on.
