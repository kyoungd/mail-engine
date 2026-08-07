# Debugging & observability — understand before fixing, fail loud

*Distilled from `marketing/CLAUDE.md` § Workflow: Errors, the LIST OF DON'T,
and the repo's recorded practice. Nothing here is new policy.*

## Debugging principles

- **An error is a signal — understand it before fixing it.** Goal #1 is
  understanding, including whether it points to a systemic issue; goal #2,
  only after, is the fix. If you can't name the specific code path, env var,
  or state that produces the signal, you don't understand it yet — don't
  propose a fix.
- **Evidence, not assumption.** Verify the cause with logs, queries, or a
  targeted experiment. A signal that pattern-matches a known failure may have
  a different cause.
- **Don't guess.** When uncertain, add logging and run it again — or say
  "I don't know yet" and name the missing data. Guessing wrong costs more
  than one more run.
- **Ask "instance or class?"** Every bug gets the question: is this a one-off,
  or the visible member of a class? Fixing the symptom while the class
  survives is how the same bug ships three times.
- **Run the thing.** The repo's record is explicit: the defects that mattered
  were surfaced by *running* the code, never by reading it. The suite is the
  check; reading is not. (Corollary: a bounded, reversible real-data run —
  `--limit 5`, a scratch DB — beats an hour of speculation.)
- **Every bug ends by leaving a test behind** at the appropriate tier — the
  failing test that reproduces it is the 🟡 gate for the fix. The suite is
  scar tissue: it grows by default, and shrinks only as a deliberate,
  recorded act (see `testing.md` § The standing rule).

## Fail loud — the observability stance

mail-engine has no log-aggregation subsystem and doesn't want one at this
size. Its observability is three deliberate mechanisms:

1. **The event stream is the record.** Append-only, replayable, versioned —
   "what happened to this contact" is a query, not a log grep. State that
   matters lands as an event, not a print statement.
2. **Anomalies raise; they are never stored verbatim or skipped silently.**
   The pattern is everywhere and is mandatory: an unrecognized vendor value is
   an error (`lob_address`), a malformed registry line aborts the scrub
   (`DncRegistryError`), an unknown event type halts the nightly, the test
   guard fails closed, an unconfigured integration seam skips *with a printed
   reason*. Silent degradation manufactures confidence; the loud version
   surfaces the bug on day one instead of after a mis-dial.
3. **Jobs report; humans read.** Every job prints its counts (stamped,
   skipped, shortfall-by-cause, covered/skipped). A run that bounds its
   coverage says what it dropped. Diagnostic `print`/logging added while
   debugging is temporary by default — the durable artifacts are the event,
   the report line, and the test.
