# DNC sample files (FTC format, hand-built 2026-08-03)

Stand-ins for the real telemarketing.donotcall.gov downloads.

**The FULL-LIST format is now VERIFIED against real bytes (2026-08-05):** the
first live downloads (all five subscribed codes, 7,334,547 lines) confirmed
`<3-digit area code>,<7-digit number>` + linefeed, no header, no CRLF — exactly
what `dnc-full-818-sample.txt` already assumed. The parser
(`seams/dnc_registry.FileDncRegistry`) is pinned to those real bytes, and
`tests/unit/test_dnc_file_registry.py` carries a skip-if-absent test over the
real `marketing/dnc-lists/2026-08-05/` snapshot itself. Note the real client
reads the portal's **zip** (CRC as completeness check); this fixture is the
unzipped payload — tests that feed the parser zip it on the fly.

⚠️ **The CHANGE-LIST format remains UNVERIFIED — do not pin a parser to it.**
Change lists are an async request/poll/fetch flow (`SubmitDeltaFileRequest`)
we have never exercised; full-list re-download is the ratified v1, so no change
file has ever been fetched. The assumed layout below came from contradictory
secondary sources:

- **Change list** (`dnc-change-818-sample.txt`, ASSUMED): one record per line,
  `<10-digit number>,<yyyy-mm-ddThh:mm:ss>,<A|D>` (A = added to registry,
  D = deleted/delisted).

Known-answer construction (against canonical `mailengine_dev`, 100,444 contacts):

- 10 of the full list's 25 numbers are REAL 818 plumber/hvac/electrician
  contacts (first 10 by id) → a scrub against this file must produce
  exactly 10 hits.
- The other 15 are `818,55501NN` — the 555 fiction range, guaranteed absent
  from the DB → exactly 15 non-matching registry rows.
- The change list delists one of those 10 (`8184218454`, flag D) and adds one
  synthetic (`8185550199`, flag A) → applying it on top of the full list must
  yield exactly 9 hits and exercise the `clear_suppression` delisting path.

⚠️ Sample ONLY: never feed to a prod scrub; the real client's first live run
uses the real portal download. When contacts are re-ingested from fresh CSVs,
ids shift — regenerate the 10 real numbers rather than trusting these.
