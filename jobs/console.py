"""The operator's menu front door (decisions.md 2026-08-05): one text app that
dispatches to the existing CLI verbs — zero business logic of its own, the
web-window thinness rule applied to a terminal. Start it with `make console`.

The one behavior this module OWNS is the onboarding walk's compliance order:
pick the starting code → PAUSE for the SAN portal purchase (only when the code
is not already owned) → register the partner → subscribe → assign → export.
The pause is structural — declining it runs nothing downstream. The walk
CONSUMES the scrubbed pool and never syncs it: DNC download + scrub is the
daily cycle's separate job (cron / menu 7), and the walk merely stops with
guidance when the picked code has no scrubbed inventory yet (the ceremony
doc's § Queued follow-up, amended from "no TUI" to "no TUI framework" by the
operator 2026-08-05; the radius derivation left the walk the same day —
`jobs/derive_area_codes` stays standalone for expansion planning).
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
# Where partners' collected-number CSVs are dropped. Sibling to both checkouts
# (the ../dnc-lists/ pattern) and gitignored for the same reason: these files
# carry real people's numbers plus the permission record behind each one.
_COLLECTED = Path(__file__).resolve().parents[2] / "collected"


def _ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def _owned_inventory() -> list[tuple[str, int, int, int]]:
    """Per owned code: (code, total contacts, dialable, available). Dialable =
    scrubbed clean and voice-callable; available = dialable and still in the
    house pool. This is the onboarding decision input — which owned code the
    partner starts in, and whether it has inventory (the radius derivation is
    expansion planning, not onboarding; jobs/derive_area_codes stays standalone)."""
    from db.session import transaction

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select s.area_code, count(c.id), "
                "count(c.id) filter (where not c.dnc_registry and not c.do_not_call "
                "  and c.dnc_checked_at is not null), "
                "count(c.id) filter (where not c.dnc_registry and not c.do_not_call "
                "  and c.dnc_checked_at is not null and c.assignment_batch_id is null) "
                "from dnc_subscriptions s "
                "left join contacts c on c.phone_e164 is not null and c.is_seed = false "
                "  and substring(c.phone_e164 from 3 for 3) = s.area_code "
                "group by s.area_code order by s.area_code"
            )
            return [(code, total, dialable, avail)
                    for code, total, dialable, avail in cur.fetchall()]


# --- the onboarding walk ------------------------------------------------------


_picked_code = ""  # the onboarding pick, carried into the subscribe step's default
_partner_name = ""  # the registered partner, carried into assign/export defaults


def _slug(name: str) -> str:
    return "-".join(name.lower().split())


def _roster() -> list[tuple[str, int | None, str | None]]:
    from config.params import HOUSE_PARTNER_ID
    from db.session import transaction

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select name, sales_rep_id, partner_code from partners "
                "where status = 'active' and id <> %s order by name",
                (HOUSE_PARTNER_ID,),
            )
            return list(cur.fetchall())


def _pick_collected_file() -> Path | None:
    """The CSV comes out of the drop folder, chosen by number or name — no paths
    to type (operator, 2026-08-06). Nothing there is a dead end worth naming: an
    empty folder means the file has not been saved yet, so print where it goes."""
    _COLLECTED.mkdir(parents=True, exist_ok=True)
    files = sorted(_COLLECTED.glob("*.csv"))
    if not files:
        print(f"no CSV files in {_COLLECTED} — drop the partner's file there first")
        return None
    print(f"files in {_COLLECTED}:")
    for i, f in enumerate(files, start=1):
        print(f"  {i}) {f.name}")
    choice = _ask("file", "1")
    if choice.isdigit() and 1 <= int(choice) <= len(files):
        return files[int(choice) - 1]
    named = _COLLECTED / choice
    if named.exists():
        return named
    print(f"no such file: {named}")
    return None


def _partner_id(name: str):
    from db.session import transaction

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from partners where name = %s", (name,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"no partner named {name!r}")
            return row[0]


def _partner_hours(name: str) -> int | None:
    from db.session import transaction

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select weekly_hours from partners where name = %s", (name,))
            row = cur.fetchone()
            return row[0] if row else None


def _pick_partner(*, allow_new: bool) -> str | None:
    """Numbered pick over the active roster — names are for humans, numbers are
    for picking (operator decision 2026-08-05: a two-founder shop's roster stays
    short forever). Returns the picked name; None means 'create new' (only when
    allow_new). A typed name passes through, so free text still works."""
    rows = _roster()
    if not rows:
        return None if allow_new else ""
    print("partners:")
    for i, (name, rep, code) in enumerate(rows, start=1):
        print(f"  {i}) {name}  (rep {rep if rep is not None else '-'}, code {code or '-'})")
    if allow_new:
        print("  n) new partner")
    choice = input(f"partner{' [n]' if allow_new else ''}: ").strip()
    if allow_new and (not choice or choice.lower() == "n"):
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(rows):
        return rows[int(choice) - 1][0]
    return choice


def _run_step(step: Callable[[], int]) -> int:
    """The CLI verbs report failures via SystemExit (argparse, unknown partner)
    or domain exceptions (ValidationError). Inside the console either one is a
    step RESULT, not a process death — translating them here is what keeps the
    menu alive after a failed verb. Ctrl-C/EOF are BaseException and still
    propagate to the menu's own handler."""
    try:
        return step()
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 0 if exc.code is None else 1
    except Exception as exc:  # noqa: BLE001 — the console boundary turns errors into text
        print(f"error: {exc}")
        return 1


def _step_register() -> int:
    from jobs.partners_cli import main

    global _partner_name
    picked = _pick_partner(allow_new=True)
    if picked:
        _partner_name = picked
        if _partner_hours(picked) is None:
            # An existing partner must leave this step assignable: without hours
            # the derived batch size has nothing to derive from (found live
            # 2026-08-06 — dev John's seeded row has no hours).
            hours = _ask("weekly dial hours (sizes the batch)", "10")
            return main(["set", picked, "--hours", hours])
        return 0
    name = _ask("partner name")
    if not name:
        return 1
    _partner_name = name
    email = _ask("report email")
    hours = _ask("weekly dial hours", "10")
    rep = _ask("main-site sales-rep id (blank if none yet)")
    code = _ask("partner code (blank if none yet)")
    argv = ["set", name, "--hours", hours]
    if email:
        argv += ["--channel", "email", "--channel-address", email]
    if rep:
        argv += ["--sales-rep-id", rep]
    if code:
        argv += ["--partner-code", code]
    return main(argv)


def _step_subscribe() -> int:
    from jobs.subscribe_area_codes import main

    codes = _ask("area code(s) to record (space-separated)", _picked_code).split()
    return main(["add", *codes]) if codes else 1


def _step_assign() -> int:
    from jobs.assignment_cli import main

    partner = (
        _ask("partner name", _partner_name)
        if _partner_name
        else (_pick_partner(allow_new=False) or "")
    )
    key = _ask("batch key (idempotent)", f"{_slug(partner)}-b1" if partner else "")
    count = _ask("explicit count (blank = derived from hours)")
    # The onboarding pick bounds the batch to the partner's code; from the bare
    # menu (no pick) the rule stays open.
    rule = {"area_code": [_picked_code]} if _picked_code else {}
    argv = ["assign", partner, "--key", key, "--rule", json.dumps(rule)]
    if count:
        argv += ["--count", count]
    return main(argv)


def _step_export() -> int:
    from jobs.assignment_cli import main

    partner = (
        _ask("partner name", _partner_name)
        if _partner_name
        else (_pick_partner(allow_new=False) or "")
    )
    out = _ask("output CSV", f"{_slug(partner)}-leads.csv" if partner else "")
    return main(["export", partner, "-o", out])


ONBOARD_STEPS: list[tuple[str, Callable[[], int]]] = [
    ("register", _step_register),
    ("subscribe", _step_subscribe),
    ("assign", _step_assign),
    ("export", _step_export),
]


def run_onboarding() -> int:
    """Walk onboarding in compliance order: pick the starting code → purchase
    pause ONLY if the code is not already owned → register → subscribe →
    assign → export. Declining the purchase runs nothing.

    The walk CONSUMES the scrubbed pool; it never syncs it — downloading and
    scrubbing DNC files is the daily cycle's separate job (cron or menu 7,
    operator decision 2026-08-06). An owned code with no scrubbed inventory
    stops at the pick; a just-purchased code ends after subscribe, because its
    file is not even provisioned yet. Either way the assign gates would refuse
    unscrubbed contacts regardless — these stops just say so up front."""
    inventory = _owned_inventory()
    if inventory:
        print("owned codes — total / dialable / available:")
        for code, total, dialable, available in inventory:
            print(f"  {code}: {total} / {dialable} / {available}")
    else:
        print("no area codes subscribed yet")
    picked = input(
        "starting code (policy: ONE, the densest for the partner): "
    ).strip()
    if not picked:
        print("Onboarding stopped — no code picked.")
        return 1
    global _picked_code
    _picked_code = picked
    row = next((r for r in inventory if r[0] == picked), None)
    new_code = row is None
    if new_code:
        confirmed = input(
            f"{picked} is not subscribed — purchase it at the SAN portal "
            "(Representative login) now, $82/code past the free five. "
            "Purchased and ready to continue? [y/N]: "
        )
        if confirmed.strip().lower() != "y":
            print("Onboarding stopped — nothing subscribed, scrubbed, or assigned.")
            return 1
    elif row[3] == 0:
        print(
            f"{picked} has no assignable inventory — it has not been scrubbed "
            "(or the pool is drained). Run 7) DNC daily cycle, or wait for the "
            "nightly cron, then re-run onboarding."
        )
        return 1
    for name, step in ONBOARD_STEPS:
        rc = _run_step(step)
        if rc != 0:
            print(f"onboarding stopped at {name} (exit {rc})")
            return rc
        if new_code and name == "subscribe":
            print(
                f"{picked} is recorded. Its registry file arrives with the next "
                "DNC daily cycle (cron, or menu 7) once the FTC provisions it — "
                "re-run onboarding after that to assign and export (the same "
                "batch key is safe to reuse)."
            )
            return 0
    print("Onboarding complete.")
    return 0


# --- the menu -----------------------------------------------------------------


def _partner_status() -> int:
    from jobs.partners_cli import main

    name = _ask("partner name (blank = all active)")
    return main(["status", *([name] if name else [])])


def _roster_action() -> int:
    from jobs.partners_cli import main

    return main(["list"])


def _assign() -> int:
    return _step_assign()


def _export() -> int:
    return _step_export()


def _reclaim() -> int:
    from jobs.assignment_cli import main

    partner = _pick_partner(allow_new=False) or ""
    reason = _ask("reason", "partnership ended")
    return main(["reclaim", partner, "--reason", reason])


def _dnc_daily() -> int:
    return subprocess.run([str(_SCRIPTS / "dnc-daily.sh")]).returncode


def _dnc_portal_status() -> int:
    return subprocess.run([str(_SCRIPTS / "dnc-status.py")]).returncode


def _subscribe() -> int:
    return _step_subscribe()


def _import_collected() -> int:
    """Item 11: a partner's own collected numbers. Conflicts resolve inline —
    the evidence is printed where the decision is made, not in a report the
    operator has to go hunting through afterwards."""
    import csv as _csv

    from service.assignment import move_contact
    from service.referrals import import_collected

    partner = _pick_partner(allow_new=False) or ""
    if not partner:
        return 1
    path = _pick_collected_file()
    if path is None:
        return 1
    with path.open(newline="") as fh:
        rows = [{**row, "sourced_by": row.get("sourced_by") or partner}
                for row in _csv.DictReader(fh)]
    if not rows:
        print("empty file")
        return 1

    report = import_collected(rows, actor="console")
    print(f"\nread {len(rows)} rows")
    print(f"  created          {report.created:>3}   new to us")
    print(f"  took custody     {report.took_custody:>3}   already in our list, unowned")
    print(f"  already theirs   {report.already_theirs:>3}   permission recorded")
    print(f"  conflict         {len(report.conflicts):>3}   held by another partner")
    print(f"  rejected         {len(report.rejected):>3}")
    for bad in report.rejected:
        print(f"    row {bad.row}: {bad.reason}")
    for cliff in report.cliffs:
        print(
            f"  ⚠ {cliff.phone} on the sheet until {cliff.expires_on} "
            f"({cliff.why}) — needs DNC clearance after that"
        )

    for conflict in report.conflicts:
        since = conflict.held_since.date().isoformat() if conflict.held_since else "?"
        print(f"\nCONFLICT  {conflict.phone}")
        print(f"  held by {conflict.held_by} since {since}")
        print(f"  activity on this contact: {conflict.activity}")
        answer = input(f"  → move to {partner}? [y/N]: ").strip().lower()
        if answer != "y":
            print("  (left where it is)")
            continue
        move_contact(conflict.contact_id, _partner_id(partner),
                     reason=f"conflict resolved in favour of {partner}",
                     actor="console")
        print(f"  moved to {partner}")
    return 0


_MANUAL = """
mail-engine console — operator manual

THE MODEL
  Contacts are the pool. The daily DNC cycle keeps the pool legal to dial.
  Partners hold BATCHES of contacts for 90 days; you watch the day-30 mark.
  None of this is partner-visible — partners only ever receive an exported
  CSV and their report emails.

ITEMS
  1  partner status   the scoreboard: holdings, each live batch (day N of 90,
                      QUIET past day 30 / activity), export + report stamps
  2  roster           the address book: every partner row and its config
  3  onboard          the full walk: pick starting code -> purchase pause (only
                      if the code is not owned) -> pick or create the partner ->
                      record subscription -> assign -> export CSV.
                      Consumes the scrubbed pool; NEVER downloads or scrubs.
  4  assign a batch   one batch to a partner. The batch key is idempotency:
                      the same key returns the same batch as a receipt —
                      a retry can never double-assign.
  5  export leads     regenerate a partner's FULL working CSV. The re-pull
                      rule: an old sheet is a liability, dial only the newest.
  6  reclaim          return ALL of a partner's holdings to the pool
  7  DNC daily cycle  download today's registry files + scrub anything due.
                      Give it to cron:  10 7 * * * scripts/dnc-daily.sh
  8  DNC portal       is the FTC subscription live / serving files
  9  subscribe        record an area code purchased at the SAN portal
 10  import collected a partner's OWN numbers from a CSV dropped in the
                      collected/ folder beside the checkout, with the
                      permission that
                      justifies calling them (who said it, when, where).
                      In their personal list they are on the sheet for 90
                      days with NO registry check — our own do-not-call
                      still applies. Conflicts resolve inline on evidence.

RULES THE SYSTEM ENFORCES (no way around them, by design)
  - on the DNC registry, opted out, or tombstoned  -> never assigned
  - DNC check older than 31 days                   -> never assigned
  - area code not subscribed                       -> never assigned
  - every refusal is counted and NAMED in the assign receipt (shortfalls)

CLOCKS
  90 days  batch custody; expiry returns unworked leads to the pool
  30 days  quiet-batch checkpoint -> status + your digest; reclaim is YOUR call
  31 days  safe-harbor wall: max age of the registry version behind any dial
  21 days  per-contact scrub recheck cadence (the daily cycle covers it)

PARTNER IDENTITY (Medusa <-> here)
  Create the roster row on the main site first; enter its sales-rep id and
  partner code when registering here. Those two keys are how closes credit.

MORE
  design: docs/partner-lead-assignment.md   decisions: docs/decisions.md
  every menu item is also a plain CLI — e.g. python -m jobs.partners_cli --help
"""


def _help() -> int:
    print(_MANUAL)
    return 0


ACTIONS: dict[str, tuple[str, Callable[[], int]]] = {
    "1": ("partner status", _partner_status),
    "2": ("roster", _roster_action),
    "3": ("onboard a new partner", run_onboarding),
    "4": ("assign a batch", _assign),
    "5": ("export leads", _export),
    "6": ("reclaim a partner's holdings", _reclaim),
    "7": ("DNC daily cycle (download + scrub)", _dnc_daily),
    "8": ("DNC portal status", _dnc_portal_status),
    "9": ("subscribe an area code", _subscribe),
    "10": ("import collected numbers", _import_collected),
    "11": ("help", _help),
}


def _menu() -> None:
    print("\nmail-engine console")
    for choice, (label, _) in ACTIONS.items():
        print(f" {choice}) {label}")
    print(" 0) quit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="console",
        description="Menu front door to the mail-engine operator CLIs.",
        epilog=(
            "Start with `make console` (sources .env). Every menu item dispatches\n"
            "to an existing verb — partners_cli, assignment_cli, the DNC scripts —\n"
            "so anything here can also be run directly; see each module's --help.\n"
            "Item 3 walks partner onboarding in the compliance order: pick the\n"
            "starting code -> SAN purchase pause (only if not already owned) ->\n"
            "register the partner -> subscribe -> assign -> export. The walk\n"
            "consumes the scrubbed pool; syncing it (download + scrub) is the\n"
            "daily cycle's separate job (cron or item 7). Expansion planning\n"
            "(which code to buy next) stays in jobs/derive_area_codes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.parse_args(argv)

    while True:
        _menu()
        try:
            choice = input("> ").strip()
        except EOFError:
            return 0
        if choice == "0":
            return 0
        entry = ACTIONS.get(choice)
        if entry is None:
            continue
        _, runner = entry
        try:
            _run_step(runner)
        except (KeyboardInterrupt, EOFError):
            print("\n(cancelled — back to menu)")


if __name__ == "__main__":
    sys.exit(main())
