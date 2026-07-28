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
- **`ingest-contact-migration-implementation.md` (rev 2** — restructured
  after its own fresh-context + codebase review found the phase sequencing
  unsatisfiable**)** — phases: 0 facts/docs (✅ DONE 2026-07-27), 1 additive
  schema+adapters+seam 🟡 (suite runs PRE-swap), 2 **the swap boundary** 🟡
  (ALL swap-dependent code — spine verbs + audience + execution re-key — plus
  the `migrate_grain` wiring land together; suite runs POST-swap from here),
  3 verify_addresses job 🟡, 4 prod merge 🔴. `migrate_grain` re-run contract
  pinned: post-swap → no-op; pre-swap with data → loud halt (ceremony
  required); pre-swap empty → swap auto-applies (fresh envs).
- **Lob AV facts (verified 2026-07-27, in design §5):** verdict enum
  `deliverable`/`deliverable_{missing,incorrect,unnecessary}_unit`/
  `undeliverable` (only `undeliverable` excludes); `delivery_point_barcode` is
  the dedupe key; ~102k backfill ≈ **$920 one-time** (one Growth AV month
  $450 + overage $0.009), separate from the print plan (stays Developer).
  Confirm exact tier prices in dashboard at purchase.
- **`partner-lead-assignment.md` rev 6 + its impl plan — APPROVED** (operator
  approval was given at the end of the rev-6 session and only *recorded*
  2026-07-28; `decisions.md` carries the entry). **Still do not build the
  phases yet:** revision 7 (twin-row stratum deletion) comes after the grain
  migration completes, and building rev 6 first means writing twin-row
  machinery in order to delete it. Migrations renumbered 0009/0010 (grain
  holds 0008). Phase 2 keeps its own 🔴 gate. **Phase 0 IS unblocked and
  should start now** — it is all non-code, and the SAN registration (NMC EIN
  39-3518688) plus the counsel hour have lead times that do not overlap with
  the grain build unless started.

## Next session

1. **Phase 1** (🟡): frozen tests first — migration `0008` (additive DDL incl.
   `is_primary` partial unique), adapters emit `trades`, `AddressVerifier`
   Protocol + Fake. NO swap wiring yet — suite stays pre-swap. Show the
   tests, get the nod, green.
2. **Phase 2** is the big one (the swap boundary — may split across sessions
   *within* the phase, but the boundary isn't claimed until all of it is
   green and the swap is wired). Then Phase 3; Phase 4 (prod merge) is 🔴
   with the dry-run report as the gate.
3. After Phase 4: partner rev 7, then the partner queue (radius script, Q6
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
