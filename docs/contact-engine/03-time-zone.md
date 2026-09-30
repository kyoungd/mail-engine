# contact-engine Upgrade — Part 3: Time zone

**Status:** APPROVED by the operator, 2026-09-30, at revision 6 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). Approval does not start the
build: its plan and tests come first. **BUILT 2026-09-30:** under an approved build plan
and an approved test gate, `0016.contact-zones.sql`, `domain/zones.py` with NANPA's file
at `domain/data/npa_report.csv`, `service/zones.py`, `jobs/zone_admin_cli.py`, and the
window in `config/params.py`; gate `tests/acceptance/test_time_zone.py`. Each §8 mutation
failed the gate. No production-backup check: production starts blank and is reloaded
(operator, 2026-09-30). While writing the gate, §6's claim that Guam and New York share
no window was found false (one hour in winter) and corrected. Two costly
decisions were put to the operator before the design (§9, answers 1 and 2), and a third
after revision 3's review (answer 3). History: Revision 1 did not pass its review (NANPA
lists two overlay codes, 986 and 930, with one zone where their area has two, and a
"shared zones" rule then fixed a wrong single zone; `opens_at` was built before any part
needs it; one count was wrong). Revision 2 did not pass (the overlay rule did not say how
to read NANPA's irregular strings; no test pinned the rep's limits). Revision 3 did not
pass: the rep's "fill in or narrow" either left a wrong single zone the rep could not
correct (a ported mobile with no state) or let the rep's own typed state narrow away the
phone's zone. Asked whose word counts, the operator chose the rep's (answer 3): revision 4
replaces "fill in or narrow" with one rule — the holding rep or an admin sets the zone,
and every setting is recorded — and adds a synthetic-file test of the overlay reading.
Revision 4 did not pass: no test asserted through `calling_hours` that a set zone replaces
the phone and state, and the comma-row fixture could be joined another way. Revision 5
pins both, applies the minor findings, and folds `zones()` into `calling_hours`. Revision
5 **passed** its review (no blocking finding); its minor findings are applied here, in
revision 6.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 5.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `c262655` (parts 0, 1 and 2 built).
A statement about the code carries its file and line.

---

## 1. Its job

Say which time zones a business could be in, who set them if anyone did, and whether a
given moment is inside the calling window in every one of them. Let the holding rep or an
admin set the zone.

| Decision | What it asks |
|---|---|
| 5.1 | No zone is assumed. Area code first, the state as a cross-check. When more than one zone is possible, the hours safe in every one. |
| 5.2 | No zone known: the rep says where the business is before the first call. No skip. |
| 5.3 | The window is 9 AM to 7 PM, the business's time, the same for every rep; an admin can change it. |
| 5.4 | Outside the window is a warning, not a block. The rep confirms; the confirmation is recorded. |
| 5.5 | *As decided 09-28:* the holding rep can fill in a missing zone, or narrow several to one; an admin can set any. *Changed 2026-09-30 by answer 3:* the holding rep's word counts — the rep can set the zone, as an admin can. |

Open items it settles: the calling-hours half of 9.16.

## 2. Its edges

| Part 3 does | Part 3 does not — who does |
|---|---|
| The zones a contact could be in, and who set them (§4.1–§4.3) | Refuse a call because no zone is known (5.2), or show the warning and record the rep's confirmation (5.4) — part 5, which opens a call and keeps its record |
| Whether a moment is inside the window in every zone, and the local times (§4.4) | Decide "may I call now": that adds the DNC status (part 2) and the sequence (part 5). When the window next opens — the card's "until when" — is built with the card |
| Setting a zone, by the holding rep or an admin (§4.5) | Expose any of it from outside — part 6 |
| | Change the assignment gate or the export: calling hours decide nothing there |

## 3. What exists, checked

| Fact | Where |
|---|---|
| Nothing in the code knows a time zone of a business. No module imports `zoneinfo` | searched `service/`, `domain/`, `jobs/`, `judgment/`, `config/` |
| A contact carries `addr_state` (free text) and `phone_e164`; door A copies the list's state; door B copies the rep's, optional; the operator's address correction and the seed upsert rewrite it | `db/migrations/0001.create-schema.sql:31`; `service/contacts.py:144`, `:287`, `:333`, `:388`; `service/rep_intake.py:221-225`; `domain/types.py:147` |
| Door B accepts any `+1` number whose area code and exchange do not start with 0 or 1 and are not N11 — Canadian and toll-free numbers included | `service/rep_intake.py:32-43` |
| Holding is `contacts.owner_id`; the house is `HOUSE_PARTNER_ID`. Part 2's report refuses the house or an unknown partner as `bad_rep` | `db/migrations/0009.partner-custody.sql:61`; `config/params.py:14`; `service/dnc.py:162-164` |
| Tunables live as constants in `config/params.py` (the 21, 31 and 90 days) | `config/params.py:19`, `:33`, `:43` |
| The clock rule: new code takes the moment as `at`, timezone-aware, and never asks the time itself | `01-intake.md` §4.6 (decision 9.15, part 1 answer 4) |
| The only hard delete of contacts is the one-time grain swap | `jobs/migrate_grain.py:442` |
| The dev list, 2026-09-30: 81,988 contacts with a phone. 78,671 have a California area code (78,036 with state `CA`); 2,140 another state's geographic code (816 with `CA`); 1,126 a toll-free code (1,039 with `CA`); 51 a code that is not a US geographic code in service — Canadian, Caribbean, not yet in service, or unassigned (45 with `CA`). 6 have no state; every other state is two capital letters | query on `mailengine_dev`, codes classed by NANPA's file |
| Python's `zoneinfo` loads all eleven zones of §4.1 on this machine | checked; **on Render not checked** — §6 |

**The numbering authority's file.** NANPA publishes every area code with its zone at
`https://reports.nanpa.com/public/npa_report.csv` (linked from
`nanpa.com/reports/npa-reports`; the copy read here is dated 09/30/2026). Its first line
is `File Date,<date>`, then the header. It has 378 US geographic area codes in service
(`COUNTRY = US`, `USE = G`, `IN_SERVICE = Y`), 41 of them California's; their `LOCATION`
is a two-letter state except `CNMI`. The `TIME_ZONE` column takes thirteen values on
those rows: `E` 168, `C` 110, `P` 52, `M` 18, `EC` 12, `CM` 6, `MP` 3, `A` 3, `(UTC+10)` 2,
`UTC-11` 1, `(UTC-10)` 1, `AK` 1, and `PT/MT only for W Wendover` 1 (775, Nevada). Area
codes that cross a zone line carry two letters (208, 219, 270, 308, 364, 423, 448, 458,
541, 574, 605, 606, 620, 701, 729, 785, 812, 850, 906, 915, 931). Toll-free and other
non-geographic codes have no zone.

**An overlay can carry fewer letters than the code it overlays:** 986 is `P` though it
overlays 208 (`MP`, all of Idaho); 930 is `E` though it overlays 812 (`EC`). NANPA's
`OVERLAY_COMPLEX` column groups codes, but irregularly: five rows hold two groups
separated by a comma (`206/564, 360/564 ` on 564), membership is not symmetric (321's row
is empty while 407's names it; 832's leaves out 621, which 713's includes; 313 and 734
are joined only through 679), and two groups name codes not in service (761, 565).

**16 CFR 310.4(c)**, read 2026-09-30 on eCFR: calls to a residence only "between 8:00 a.m.
and 9:00 p.m. local time at the called person's location". The window of 9 AM to 7 PM
lies inside it. State and Sunday rules stay open with counsel (9.16).

## 4. The design

### 4.1 The zone table: NANPA's file, as published (answer 1)

The file is committed as `domain/data/npa_report.csv`, unedited. `domain/zones.py` reads
it once, at import, through `load(path)`, which the tests call on synthetic files; and keeps the US geographic in-service rows. Each kept row's
`TIME_ZONE` maps to zones by a fixed table:

| Value | Zones |
|---|---|
| `E` | America/New_York |
| `C` | America/Chicago |
| `M` | America/Denver; **America/Phoenix when the row's `LOCATION` is AZ** (Arizona keeps no daylight time) |
| `P` | America/Los_Angeles |
| `EC`, `CM`, `MP` | the two letters' zones |
| `PT/MT only for W Wendover` | America/Los_Angeles, America/Denver |
| `A` | America/Puerto_Rico |
| `AK` | America/Anchorage |
| `(UTC-10)` | Pacific/Honolulu |
| `(UTC+10)` | Pacific/Guam |
| `UTC-11` | Pacific/Pago_Pago |

**The import fails loud** when: the first line is not `File Date`; a kept row's
`TIME_ZONE` is not in the table (an empty one included); an Arizona row is not `M`; a
kept row's `LOCATION` is neither two capital letters nor `CNMI`; or a kept `NPA_ID`
repeats. Rows the filter drops are not read; some carry values outside the table (`N`,
`CMP`, blank). A refreshed file that drops rows another way is caught by the gate's pinned
count (§7); a refresh updates that pin by hand, after reviewing what changed.

Then, in this order:

1. **Hand additions**, first, so that a hand-added code later joined to a group passes
   its addition on. An official clock NANPA's letters miss is added; an unofficial
   local custom is not (§6). Each only adds:

   | Area code | Adds | Why |
   |---|---|---|
   | 928 | America/Denver | The Navajo Nation, in 928, keeps daylight time; the rest of Arizona does not |
   | 907 | America/Adak | The western Aleutians are an hour behind the rest of Alaska |

   A hand-addition code missing from the kept rows fails the import.

2. **Overlay groups.** A row's members are its own `NPA_ID` and the three-digit numbers in
   its `OVERLAY_COMPLEX` string, whatever separates them; members not kept are ignored. Two
   kept codes are in one group when a chain of rows joins them — a row names both, or
   each is joined to a third (so 313 and 734 join through 679, and 206 and 360 through
   564's row). Every code in a group gets the union of the group's zones. On the
   09/30/2026 file this changes only 986 (adds Denver) and 930 (adds Chicago).

Those eleven zones are the only zones part 3 knows (`ZONES`). **A state's zones** are the
union of its area codes' zones, as read above; `CNMI` is read as the postal `MP`. No
second table is kept.

### 4.2 The zones a contact could be in (decision 5.1)

- **A** = the area code's zones; none if there is no phone, or its area code is not a US
  geographic code in service (toll-free, Canadian, unknown).
- **S** = the state's zones; none if `addr_state`, trimmed and upper-cased, is not a state
  in the file. States are postal codes: `MP` matches the Northern Mariana Islands; the
  text `CNMI` does not.

**The zones are A ∪ S** — none when both are none. The phone and the address are each
evidence of where the business is; the hours must be safe wherever either points
(decision 5.1: "the more restricted time window that accomodates both timezone"). An
intersection was rejected: a ported mobile (865, Eastern, for a Nashville business, `TN`)
would keep only Eastern, an hour off.

Examples: 818 and `CA` → Los Angeles. 214 and `TX` → Chicago and Denver. 800 and `CA` →
Los Angeles. 480 and `CA` → Phoenix and Los Angeles. 986 and no state → Denver and Los
Angeles. 800 and no state → none. For California, where every code and the state give
Los Angeles alone, the union changes nothing. When the evidence is wrong — a 212 mobile
for a Los Angeles business with no state — the rep sets the zone (§4.5).

### 4.3 A zone someone set (decision 5.5 as changed by answer 3)

A set zone is a row in `contact_zones`, append-only. The latest row for a contact — the
highest `seq`, never the caller's `at` — replaces §4.2 entirely: the contact's zones are
that one zone. The row records the zone, the actor, the rep (null when an admin set it),
and `at`. Nothing else writes it. The rows are the log of zone changes the admin view
(part 6) reads. A set zone outlives a change of phone or state; §6.

### 4.4 Calling hours (decisions 5.1, 5.3)

`CALLING_WINDOW_START = time(9)` and `CALLING_WINDOW_END = time(19)` in `config/params.py`
(answer 2). A local time is inside when `START <= t < END` — 7:00 PM is outside.

`calling_hours(contact_id, at)` returns:

| Field | Meaning |
|---|---|
| `zones` | as §4.3 when set, else §4.2 |
| `set_by` | when set: the actor, the rep, and `at` of the latest row; else `None` |
| `local` | `at` in each zone, by `zoneinfo` — no offset is written in code |
| `inside` | `True` when `at` is inside in **every** zone; `False` when outside in any; **`None` when no zone is known** — never `True` |

`at` without a time zone (`tzinfo is None`, as the verbs of parts 1 and 2) raises
`ValidationError('bad_time')`; no such contact raises `no_contact`.

### 4.5 Setting a zone (decisions 5.2, 5.5 as changed by answer 3)

`set_zone(contact_id, zone, at, *, rep=None, actor=None)`, in one transaction, the contact
locked `for update`, so the holder check cannot interleave with a change of holder
(`service/custody.py:49` changes it by updating the contact). A rep passes `rep`, and the
row's actor is the rep id as text, as part 2's report does (`service/dnc.py:174`); an
admin passes `actor` and no `rep`. Refused, writing nothing:

| Code | When |
|---|---|
| `bad_time` | `at` has no time zone |
| `bad_actor` | both `rep` and `actor` are given, or neither (or `actor` is blank) |
| `bad_zone` | `zone` is not in `ZONES` |
| `no_contact` | no such contact |
| `bad_rep` | `rep` is the house or not a partner, as part 2's report (an inactive partner who still holds the contact may set it) |
| `not_yours` | `rep` is given and the contact's `owner_id` is not `rep` |

Otherwise it appends the row and returns `"set"`, whatever the phone, the state, or an
earlier setting said. A rep with no zone known is "saying where the business is" (5.2);
a rep or an admin can correct any zone. The admin reaches it with
`python -m jobs.zone_admin_cli show <contact_id>` and
`set <contact_id> <zone> [--actor young]` (`--actor` defaults to `young`, as
`assignment_cli`'s does).

## 5. Parts 1 and 2

Neither changes. Part 3 reads what doors A and B stored.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| A rep can set a wrong zone | Accepted (answer 3): the rep's word counts. The row records who and when; an admin or the rep can set it again; outside hours is a warning either way (5.4) |
| A set zone stays when the phone or state later changes (the operator's address correction, `service/contacts.py:388`) | Left: it records where the business is. It can be set again |
| Evidence that points to one wrong zone — a ported mobile with no usable state (door B's state is optional free text, so "Tennessee" gives none) | `inside` follows the phone until the rep or an admin sets the zone |
| A new area code NANPA adds after the committed copy | It reads as unknown, so the state decides, or the rep says. Refreshing is replacing the file; its import fails loud on a new kind of entry |
| `zoneinfo` on Render needs the system's zone data | **Not checked.** A test loads all of `ZONES`; if Render's image lacks the data, the hosting step raises it (no new dependency added now) |
| Zones far apart share little or no window (Guam with New York: one hour in winter, 6 to 7 PM in New York; none in summer) | `inside` is `False` most of the day; the rep sets the zone, or the warning stands (5.4) |
| Places that keep an unofficial clock the file does not show: Phenix City, AL (334, `C`) keeps Eastern; Kenton, OK (580, `C`) keeps Mountain; Hyder, AK; northwest Culberson County, TX (432, `C`; covered once the state `TX` joins) | Left, by §4.1's rule: at most an hour, inside the legal 8 to 9 (§3). The rep or an admin can set the zone |
| Business hours, holidays, Sundays, state rules | Not part 3's; state and Sunday rules stay with counsel (9.16) |

## 7. Tests, written first

`tests/acceptance/test_time_zone.py`, the gate. Every `at` is passed in UTC.

| Test | Pins |
|---|---|
| The file reads | exactly 378 kept codes on the committed file (a refresh updates this pin by hand, §4.1); every California code gives Los Angeles only |
| Fails loud | synthetic files: a first line other than `File Date`; a kept row with a value outside §4.1's table, and with an empty one; an Arizona row not `M`; a bad `LOCATION`; a repeated `NPA_ID`; a hand-addition code missing — each fails the import |
| The map | one code per `TIME_ZONE` value; Arizona's `M` giving Phoenix; 775 exactly Los Angeles and Denver; 928 exactly Phoenix and Denver; 907 exactly Anchorage and Adak |
| Overlays, real file | 986 exactly Denver and Los Angeles; 930 exactly New York and Chicago |
| Overlays, synthetic file | code X with an empty group string, named only on Y's row, Y carrying a zone X lacks → X gets it; **a row X reading `X/Y, X/Z ` (trailing space), Y's and Z's own strings empty, Z carrying a zone Y lacks → Y gets it** (the comma is the only link); a chain X–Y on one row, Y–Z on another → X gets Z's zone; a member not kept → ignored, no failure; row X's string `Y/Z` without X → X is joined to them; 928-style: a hand-added code in a group → its partner gets the addition |
| States | `TX` Chicago and Denver; `AZ` Phoenix and Denver; `CA` Los Angeles; `MP` Guam |
| §4.2 | none/none; phone only; state only; 214 + `TX` → both; 480 + `CA` → both; 865 + `TN` → New York and Chicago; toll-free + state; lower-case and padded state |
| A set zone | through `calling_hours`: 212, no state, set Los Angeles, winter, 8:30 AM Pacific → `inside` `False`; 480 + `CA`, set Los Angeles, 6:30 PM Pacific in winter → `inside` `True`, `zones` Los Angeles alone, `set_by` the setter's actor, rep, and `at`; of several, the highest `seq` wins even when an earlier row carries a later `at` |
| Inside | 9:00 inside; 18:59 inside; 19:00 outside; 8:59 outside — in Los Angeles, on a winter and a summer date; `local` is each zone's wall-clock time (8:59 in Los Angeles for 16:59 UTC in winter) |
| Every zone | 480 + `CA` in winter: 8:30 AM Pacific → `False`; 6:30 PM Pacific → `False`; noon → `True` |
| No zone | `inside` is `None`; Guam with New York at noon in New York is `False`, not `None` |
| Setting | each refusal code writes nothing, `bad_actor` in its three forms and `bad_rep` in its two (the house, an unknown partner) included; a rep's row carries the rep id as actor; the holding rep sets a zone over the phone's single zone (212, no state → Los Angeles); over an earlier setting; with none known; an inactive holding partner may set; an admin (`rep` `None`) sets over a rep's; a rep not holding → `not_yours` |
| The clock | a naive `at` raises `bad_time` in `set_zone` and `calling_hours`; a missing contact raises `no_contact` in `calling_hours` and `set_zone` |
| Zones | every zone in `ZONES` loads in `zoneinfo`; the migration's check list equals `ZONES` |

## 8. Done means

The gate green; `make test`, `make e2e`, `make lint` clean; mutation checks each failing a
test — drop the Arizona rule; the 928 addition; the overlay union; read a group one way
only; split the group string on `/` only; join groups one row deep only; the state from
the union (S dropped from A ∪ S); the `None` for no zone; the holder check; set zone by latest `at` instead of
`seq`; `calling_hours` ignoring the set zone; the row's own code left out of its group — `0016` applied to `mailengine_dev`. No production-backup check: production starts from
a blank database and its data is reloaded (operator, 2026-09-30).

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How far should the area-code table reach? | **Answered 2026-09-30: the national table.** Offered "CA codes + state table" (recommended), "National area-code table", or "California only, no state table". The numbering authority's own file then made it cheap (§4.1). |
| 2 | How is the 9 AM to 7 PM window changed? | **Answered 2026-09-30: a setting in code**, `config/params.py`, changed by an edit and a deploy. Offered that (recommended) or a stored admin setting with a command and history. |
| 3 | When a rep knows where the business is and the data disagrees, whose word counts? | **Answered 2026-09-30: the rep's.** The holding rep can set the zone, recorded with who and when. Offered that (recommended), "Keep 5.5 as written" (fill in or narrow; a wrong single zone waits for an admin), or "Rep can only add zones". |

## 10. The migration, `0016.contact-zones.sql`

```sql
create table contact_zones (
  seq         bigint generated always as identity primary key,
  contact_id  uuid not null references contacts(id) on delete cascade,
  zone        text not null check (zone in (
                'America/New_York', 'America/Chicago', 'America/Denver',
                'America/Phoenix', 'America/Los_Angeles', 'America/Anchorage',
                'America/Adak', 'Pacific/Honolulu', 'America/Puerto_Rico',
                'Pacific/Guam', 'Pacific/Pago_Pago')),
  actor       text not null,
  rep_id      uuid references partners(id),
  at          timestamptz not null
);
create index contact_zones_contact_idx on contact_zones (contact_id, seq);
grant select on contact_zones to me_user_ro;
```

Additive; writes no existing row.

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 5.3 | Add: the window is a setting in code, changed by a deploy (answer 2) |
| 5.5 | Replace: the holding rep can set the zone, as an admin can; every setting is recorded (answer 3). The old line moves to §10 |
| 9.16 | The area-code table is NANPA's file with two additions (§4.1); the calling hours were checked against 16 CFR 310.4(c) on 2026-09-30. State and Sunday rules stay open |
| `00-purpose.md`, `00-interface.md` job 3 | "fill in or narrow" becomes "set"; the interface's two rows "Fill in a missing zone, or narrow several to one" (action) and "Set any zone" (admin action) become one, "Set the zone — the holding rep or an admin"; "the calling window — admin setting" becomes "a setting in code" |
| `00-interface.md` §3, the card | "until when — from 2, 3, 5": part 3 supplies the zones and `inside`; when the window next opens is built with the card |

## 12. Safety properties

Each revision is checked against these before review.

1. `inside` is never `True` when any of the contact's zones is outside the window.
2. No zone is assumed: with none known and none set, `inside` is `None`, never `True`.
3. Only the holding rep or an admin sets a zone, and every setting is a recorded row with
   who and when; nothing else changes a contact's zones but its phone, its state, and a
   refresh of the committed file.
4. The zone table fails loud on anything it cannot read, and never drops a zone NANPA
   lists for a code or for any code joined to it in an overlay group; the hand additions
   only add.
5. Local times come from `zoneinfo` at the moment; no offset is written in code.
6. When no zone is set, the phone and the state only add zones; neither can remove one
   the other gives.
