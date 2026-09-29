# contact-engine Upgrade — Part 0: Foundation

**Status:** APPROVED by the operator, 2026-09-29 (offered approve, review once more, or
read it first; chose approve: "A."). Approval of the design does not start the build,
which is the marketing project's work. Rewritten 2026-09-29 as the removals and what
the removals need, after the first version did not pass its review; then corrected from
a second review. Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in
[the decision record](../sales-partner-dialer-decisions.md) and are named here by
number.
**Checked against:** contact-engine's code at commit `4b6d5b9`, branch `main`, read
only. Nothing under `marketing/` was changed or run. Paths are under
`marketing/mail-engine/`. A statement about the code carries its file and line; a
statement about a whole file carries the file.

---

## 1. Its job

Give the other parts clean ground: a branch that carries contact services only
(decision 2.3).

| Delivers | |
|---|---|
| The branch | |
| A command that loads a contact list | So the upload page can go |
| The removals | The web pages, the messages, the mail code |
| A nightly that runs without mail | |

It adds no rule, no table, and no migration. It adds three files, each because a
removal needs it: the command that loads a list (step 1), and two files that hold kept
code moved out of removed files (steps 3 and 5).

**What the branch cannot do after this part, until a later part builds it:**

| Cannot | Why | Built again in |
|---|---|---|
| Record an opt-out, a note, an outcome, or a next action | The web pages are the only callers of `suppress`, `record_note`, `record_outcome`, and `set_next_action` (`web/api.py:247, 252, 258, 263, 469, 485-488`; searched). The functions stay. | Parts 2 and 5 |
| Send any message | Step 3 | The website, with part 6 |

Production is not affected: it runs from `main`. These are gaps during development, and
the branch is not deployed until the upgrade is complete (decision 2.9).

**Not in this part** (decision 2.8): the clock rule and the rule for a request sent
twice. Each is built in the part that first needs it.

## 2. The branch

| Piece | Design |
|---|---|
| Cut from | `main`, at its head |
| Before cutting | `main` has three changed files not yet committed: `creative/README.md`, `docs/INSTALL.md`, `docs/direct-marketing-101.md`. They are committed to `main` first (operator, 2026-09-29, offered commit, set aside, or discard: "A."). |
| Name | `contact-engine`. Proposed; the operator has not been asked about the name by itself. |
| The main line | Changed by one commit only, the three files above. It keeps mail, the web pages, and the messages. |
| Where the branch is worked on | The development copy, `marketing/mail-engine`. **Never the production copy,** `marketing/mail-engine-production` (`scripts/backup.sh:28`), and never with a `.env` that names the production database. Which branch the production copy is on was not checked; it is outside the folder that was read. |
| Production | Stays on `main` until hosting replaces it. Nothing in this part changes what runs in production. |
| Tests on the branch | The test service runs on pushes to `main` and on pull requests (`.github/workflows/ci.yml:14-17`). On the branch the tests are run by hand, `make test` and `make lint`, after each step. |
| The database | No table is dropped, no row deleted, no migration added. The newest migration stays `0013` (`db/migrations/0013.partner-dnc-snapshots.sql`). |

---

## 3. The steps

**The rule for every step:** the step removes the code, changes what calls it, and
deals with its tests, all together. After each step the test suite passes and nothing
left imports anything removed.

### Step 1. Add the command that loads a list

Today the only way to load a list is the upload page (`web/api.py:496-499`), which
hands the file to `load_list` (`web/api.py:106-111`).

| Piece | Design |
|---|---|
| File | `jobs/intake_cli.py`, new |
| What it calls | `service.contacts.load_list` (`service/contacts.py:84`), unchanged |
| Use | `python -m jobs.intake_cli <file> --source cslb-ca` |
| The file | The form the converters in `intake/` write. The converters keep their own commands (`intake/cslb_ca.py:116`, `intake/fbn_ca.py:90`). Their help text, which says to load through the web page (`intake/cslb_ca.py:124`, `intake/fbn_ca.py:97`), names the new command. |
| What it prints | The four counts `load_list` returns: loaded, deduped, invalid, suppressed (`domain/types.py:130-134`). It gives no reason for each row; `load_list` does not return one. |
| A source it does not know | `load_list` refuses before reading a row and names the sources it knows (`service/contacts.py:63-75`). The command prints that and ends with an error. |
| `--help` | Usage and examples |
| Tests, written first | It loads `tests/e2e/fixtures/cslb-partner-journey.csv` and prints the counts. The same file loaded twice loads nothing the second time. An unknown source is refused and nothing is written. |

### Step 2. Remove the web pages

| Removed | `web/` |
|---|---|
| What imports it | Tests only. No kept code imports `web` (searched). |
| Changed with it | The `run` target (`Makefile:19`, and the `.PHONY` line, `Makefile:2`); `web` in the type checker's list (`pyrightconfig.json`); the settings the test service sets for the web pages (`.github/workflows/ci.yml:41-51`) |

### Step 3. Remove the messages

| Removed | `judgment/`, `service/nudges.py`, `seams/email_sender.py`, `seams/sender.py`, `seams/nmc_demos.py`; `FakeSender` and `FakeDemosClient` (`seams/fakes.py:91`, `:183`) |
|---|---|
| What imports them | `jobs/nightly.py:13-14, 18, 20`; `jobs/nightly_cli.py:88, 104`; `jobs/partners_cli.py:307` |
| The nightly | Loses its last two steps, the digest and the partner report (`jobs/nightly.py:65-70`), and the `sender`, `demos_client`, and `as_of` it took for them |
| The nightly's command | Loses the two functions that built them (`jobs/nightly_cli.py:79-106`), and where it calls them and passes what they built (`jobs/nightly_cli.py:176-179, 182`) |
| Status | The list of what counts as activity moves from `judgment/rules/batch_checkpoint.py:16-21` to a new file, `derivation/activity.py`, unchanged. The "last report" stamp comes out (`jobs/partners_cli.py:314, 321, 367`). |

**What goes with the messages.** All twelve rules of the digest (`judgment/rules/`),
and the partner report. None is replaced on the branch until part 6 and the website.
Production keeps all of them, on `main`.

| Rule, and what it tells the operator | About |
|---|---|
| `dnc_version_alert`: a DNC file is getting old, at 24 days (`config/params.py:69`) | Calling. The 31-day block on giving out contacts stays (`config/params.py:33`). |
| `batch_checkpoint`: a batch past day 30 with no activity | Calling. Status still marks it "QUIET past day 30" (`jobs/partners_cli.py:358-359`). |
| `orphan_events`: events that matched no contact | The nightly's matching step, which is kept |
| `activation_stalled`, `activation_partial`: a customer who never finished setting up | Customers |
| `hot_response`, `quiet_reengage`, `lost_aging`, `demo_no_show`: a responder to answer, a thread gone quiet, a contact to mark lost, a missed demo | Responses to mail and the demo line |
| `approval_pending`, `wave_anomaly`, `returned_mail` | Mail |
| The partner report, by email to each rep | Reps. The website composes and sends any report (decision 1.7). |

### Step 4. Remove the mail feeds and the address check

| Removed | `jobs/sync.py`, `jobs/verify_addresses.py`, `seams/response_feed.py`, `seams/lob_status.py`, `seams/posthog.py`, `seams/address_verifier.py`, `seams/lob_address.py`; `FakeResponseFeed` and `FakeVerifier` (`seams/fakes.py:77`, `:98`, and the import at `:17`) |
|---|---|
| What imports them | `jobs/nightly.py:11-12, 15, 19`; `jobs/nightly_cli.py:26-27, 74` |
| The nightly | Loses its first two steps (`jobs/nightly.py:36-44`), and the `feeds`, `since`, and `verifier` it took for them |
| The nightly's command | Loses the feeds, the address check, `--since`, and its refusal to run with no feed (`jobs/nightly_cli.py:39-76, 144-157`). `--dry-run` (`jobs/nightly_cli.py:132-136, 160-162`) reported which feeds were set up; it now reports whether the customer feed is set up, and runs nothing. |

### Step 5. Remove the drops and the waves

| Removed | `jobs/drop.py`, `jobs/seed_cli.py`, `service/waves.py`, `seams/print_api.py`, `seams/lob.py`; `FakePrintApi` (`seams/fakes.py:28`, and the import at `:18`); everything in `service/execution.py` except `recompute_state` |
|---|---|
| What imports them | `service/execution.py:26, 28`. `jobs/drop.py` and `seams/lob.py` were imported by `web/` only. |
| Kept | `recompute_state` (`service/execution.py:35`) moves to a new file, `service/state.py`, unchanged. `jobs/nightly.py:22` imports it from there. |
| Changed with it | The `seed-contacts` and `e2e-mail` targets (`Makefile:40, 51`). Every test that imports `recompute_state` imports it from the new file; that is a change of one line each and of no check. |

### Step 6. Remove the artwork and the AI client

| Removed | `creative/`, `ai/` |
|---|---|
| What imports them | Nothing (searched) |
| Changed with it | `ai` in the type checker's list |

### Step 7. The console

Kept, without its item that creates a rep on the website (operator, 2026-09-29: "It is
useful."; offered keep without item 11, keep as it is, or remove: "A."). The website's
roster is the one place a rep is added (decision 1.8).

| # | Item | After this part |
|---|---|---|
| 1 | Status | Works, with the change in step 3 |
| 2 | Roster | Unchanged |
| 3 | Onboard | Its optional first step, which creates the rep on the website (`jobs/console.py:317-325`), is removed. With it go the rep id it remembered for the register step (`jobs/console.py:65, 109, 122, 219`), so that step asks for the id with nothing filled in, and the message that points to menu 11 (`jobs/console.py:232`). The rest is unchanged: pick a code, register, subscribe, assign, export. |
| 4, 5, 6 | Assign, export, take back | Unchanged |
| 7 | Daily cycle | Unchanged. It runs `scripts/daily-run.sh` (`jobs/console.py:408-409`), which refuses any database but production's (`scripts/daily-run.sh:52-56`). On the branch it therefore refuses, and its test shows that it does. |
| 8, 9 | DNC portal, subscriptions | Unchanged |
| 10 | Help | Its text is brought up to date: the digest, the report emails, and menu 11 (`jobs/console.py:504, 508, 535, 540`) |
| 11 | Create a rep on the website | Removed (`jobs/console.py:103-124, 566`), with `create_sales_rep` (`seams/nmc_admin.py:111`). The login at the console's door and the reading of the roster stay. |

### Step 8. What is around the code

| File | Change |
|---|---|
| `.env.example` | The settings read only by removed code come out: `WEB_PORT`, the `LOB_` keys, the `POSTHOG_` keys, the `SMTP_` settings, `NMC_BOOKING_URL`, `NMC_API_KEY`; and the comment that names `DROP_PASSWORD` (line 8) |
| `scripts/daily-run.sh` | Its help text names the digest, the partner reports, and the DNC alert (lines 21, 28). The text only; its three steps are unchanged. |
| `Makefile` | The `integration` target (`:47-49`) comes out with `tests/integration/` |
| `.github/workflows/ci.yml` | The settings for removed code come out (`:41-51`) |
| contact-engine's own `docs/` folder | Left as it is. Its documents describe the main line. |
| `scripts/partner-rehearsal.sh` | Removed. It rehearses the partner report by email. |
| `pyrightconfig.json` | `judgment` comes out of the list, with `web` and `ai` |
| `README.md` | Says what the branch is |
| `pyproject.toml` | The packages it lists are left alone. Part 6 decides what the interface needs. |

---

## 4. The nightly, after the steps

| Today (`jobs/nightly.py:36-70`) | After |
|---|---|
| 1. Read the mail feeds | Removed, step 4 |
| 2. Check addresses | Removed, step 4 |
| 3. The DNC check, when a DNC reader is handed in | **Kept, unchanged.** The command hands in none today (`jobs/nightly_cli.py:181`); the daily script runs the check as its own step. |
| 4. Match events that have no contact | Kept |
| 5. The customer feed, when it is set up | Left as it is until part 4 (operator, 2026-09-29: "a"; §8, item 5). The operator chose that the website tells contact-engine of a sale; open question 9.2 is why that is not yet designed. |
| 6. Work out each contact's stage | Kept |
| 7. Take back expired batches | Kept |
| 8. Take back sold contacts | Kept. Part 4 changes it (open question 9.1). |
| 9. The digest | Removed, step 3 |
| 10. The partner reports | Removed, step 3 |

---

## 5. The tests

There are 77 test files. About half of them import code that is removed (searched: 38
files under `tests/`). Three kinds:

| Kind | Rule |
|---|---|
| **A.** The test is about removed code | Deleted with the code, in the same step. This holds for a whole file, for one test in a kept file, and for one check in a kept test. |
| **B.** The test is about kept behaviour, and uses removed code to set up or to look | Kept. The part that used removed code is pointed at kept code. No check is loosened. |
| **C.** The test is about a command this part rewrites | Rewritten first, then the command |

The files were sorted by what they import, and the ranges below were read. Each file is
read in full at build. **Every change of kind B is shown to the operator before it is
made. A test of removed code is deleted without asking, whether it is a whole file or
sits inside a kept file.** (Operator, 2026-09-29, offered "Only the changed checks",
"Everything", or "Nothing"; chose only the changed checks: "A.")

| Kind | Files |
|---|---|
| A | `tests/acceptance/`: `test_approval_hash`, `test_batch_checkpoint`, `test_digest_delivery`, `test_dnc_version_alert_per_code`, `test_duplicate_names`, `test_execute_wave`, `test_grain_audience`, `test_jobs`, `test_judgment_discipline`, `test_judgment_rules`, `test_partner_report`, `test_partner_report_registry`, `test_seed_pieces`, `test_verify_addresses`, `test_wave_lifecycle`, `test_wave_proofs`, `test_web_api`. `tests/unit/`: `test_av_gate`, `test_composer`, `test_email_sender`, `test_execution_helpers`, `test_lob`, `test_lob_address_mapping`, `test_lob_status_feed`, `test_posthog`, `test_seams`, `test_waves_helpers`. `tests/e2e/test_journey`. `tests/integration/`, all of it. |
| A, inside a kept file | `test_partner_assignment` (`:544-563`, `:585-603`: the digest). `test_partner_custody` (`:276-317`: who the digest writes to). `test_suppression_split` (`:529-533`: a web route). `test_dnc_list_age` (`:23`, `:189`, and the tests at `:197` and `:213`: the alert). `test_recompute` (`:72-91`, its last check: "do not mail" and the mail audience). `tests/e2e/test_partner_journey` (`:228-257`: the report email and its stamp; the fakes and the sender passed at `:199-206`, `:268-271`). |
| B | `test_contacts` (`:144-150`), `test_suppression_split` (`:24, 55`), `test_grain_intake` (`:343-345, 404-405`), `test_partner_assignment` (`:502-522`: the nightly's order), `tests/e2e/test_partner_journey` (its list is loaded through the new command) |
| C | `tests/unit/test_nightly_cli`, `tests/unit/test_console`, `tests/unit/test_nmc_admin` (`:58`), `tests/acceptance/test_partners_status` (read at build: it does not name the "last report" stamp, searched) |

**The hard case in kind B.** Three files look at the mail audience
(`service/waves.py:182`, `resolve_audience`), which is removed, to ask something that
still matters: `test_contacts`, `test_suppression_split`, `test_grain_intake`. What
matters for calling is whether the contact can be given to a rep, so a check of "is this
contact left out?" is pointed at the assignment's own rule. A check that is only about
mail is kind A. `test_grain_intake.py:343-345` asks which trades a contact is found
under, not whether it is left out; what it is pointed at is decided when it is shown.

`tests/conftest.py` and `tests/guard.py` name the print service's keys. They are read at
build.

---

## 6. Left in place

Mail code inside files that are kept. Nothing calls it after the steps. It is left
because taking it out changes kept files and their tests, for no gain to any part.

| Left | Where |
|---|---|
| The wave and pipeline queries | `service/queries.py`, the whole file. After the steps no kept code imports this file. Part 6 will want its timeline and search. |
| The seed contacts and the address update | `service/contacts.py:305, 346, 362` |
| "Report email", asked when a partner is registered | `jobs/console.py:241, 244` |
| The "last report" column | The `partners` table |
| The mail tables | The database |

---

## 7. Done means

| Check | How it is shown |
|---|---|
| The branch exists, cut from a committed `main` | |
| `jobs/intake_cli.py` loads the fixture file | Its tests pass |
| Nothing left imports anything removed | A search, and the type checker passing |
| Every test left passes; the linter and the type checker are clean | `make test`, `make lint` |
| `make e2e` passes | With `test_partner_journey` loading its list through the new command |
| The nightly runs to its end with no mail setting present | A test |
| Every console item left does what §3 step 7 says | A test for each. For item 7, that it refuses. |
| `main` has one new commit, the three files, and production still runs its jobs | |

---

## 8. For the operator, at approval

| # | | Proposed |
|---|---|---|
| 1 | The branch's name | `contact-engine`. Put to the operator on 2026-09-29 as going ahead unless objected to, with items 4 and 7. |
| 2 | ~~The rule for tests (§5)~~ | **Answered 2026-09-29:** only the changed checks are shown first: "A." |
| 3 | ~~The twelve rules and the partner report absent on the branch until part 6 (step 3)~~ | **Not a question** (decision 2.9). A gap during development. |
| 4 | The mail code left in place (§6) | Proposed: left in place. Going ahead unless objected to. |
| 5 | ~~The customer feed left as it is until part 4 (§4)~~ | **Answered 2026-09-29.** Offered "Leave it as it is" or "Remove it now"; chose leave it: "a". The nightly read stays on the branch, untouched, until part 4 designs its replacement. The operator's choice that the website tells contact-engine of a sale stands. |
| 6 | ~~No way to record an opt-out or a note on the branch until parts 2 and 5 (§1)~~ | **Not a question** (decision 2.9). A gap during development. |
| 7 | The command that loads a list is added here and not in part 1 | Proposed, going ahead unless objected to: the web pages cannot go without it. What loading does is part 1's. |
