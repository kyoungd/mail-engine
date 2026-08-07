"""The DNC scrub (partner-lead-assignment.md §6/S-9, Phase 2). Runs DAILY —
cron/CLI, never a route — and is a cheap no-op when nothing has crossed the
21-day threshold, which is what makes "a couple of missed runs cost nothing"
true. The subscription — not the assignment — bounds the scrub: every contact
in a subscribed area code is covered, assigned contacts first, because the
§310.4(b)(3) safe harbor demands calling against a registry version no more
than 31 days old and the assignable pool must stay warm.

Idempotency is the events table's `unique (source, external_id)`:
`dnc:<contact_id>:<registry_version>` — the same version twice appends nothing.
A hit sets `dnc_registry` on the row (the row IS the phone since the grain
merge) and ends any live assignment via `set_owner`. A previously-hit number
ABSENT from the current version clears through `clear_suppression`, keyed
contact + version like the check event (S-9's delisting writer).
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from config.params import DNC_RECHECK_DAYS, HOUSE_PARTNER_ID
from db.session import transaction
from seams.dnc_registry import DncRegistry
from service.contacts import clear_suppression
from service.custody import set_owner
from service.ingestion import append_event


@dataclass(frozen=True)
class DncReport:
    checked: int = 0
    hits: int = 0
    cleared: int = 0


def _national(phone_e164: str) -> str:
    """+18185550123 -> 8185550123 (the registry lists 10-digit national numbers)."""
    return phone_e164.removeprefix("+1")


def dnc_refresh(registry: DncRegistry, *, limit: int | None = None) -> DncReport:
    """One scrub pass: re-check contacts in subscribed area codes whose
    `dnc_checked_at` is older than the 21-day threshold (or never set),
    assigned contacts first. Each contact commits in its own transaction, so
    one bad row cannot roll back the rows already stamped."""
    version = registry.version()

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select area_code from dnc_subscriptions")
            subscribed = [r[0] for r in cur.fetchall()]
            if not subscribed:
                return DncReport()

            cur.execute(
                "select id, phone_e164, owner_id, dnc_registry, "
                "substring(phone_e164 from 3 for 3) as area_code "
                "from contacts "
                "where phone_e164 is not null and is_seed = false "
                "and substring(phone_e164 from 3 for 3) = any(%s) "
                "and (dnc_checked_at is null or dnc_checked_at < now() - "
                "make_interval(days => %s)) "
                "order by (owner_id = %s), id "  # assigned (non-house) first
                + ("limit %s" if limit is not None else ""),
                (subscribed, DNC_RECHECK_DAYS, HOUSE_PARTNER_ID)
                + ((limit,) if limit is not None else ()),
            )
            due = cur.fetchall()

    # One listed() call per area code over OUR due numbers — the registry file
    # streams past our set, never the reverse (decisions.md 2026-08-03). A
    # DncRegistryError here aborts before anything is stamped.
    by_code: dict[str, set[str]] = {}
    for _, phone, _, _, area_code in due:
        by_code.setdefault(area_code, set()).add(_national(phone))
    on_registry = {
        code: registry.listed(code, frozenset(numbers))
        for code, numbers in by_code.items()
    }

    checked = hits = cleared = 0
    for contact_id, phone, owner_id, already_listed, area_code in due:
        hit = _national(phone) in on_registry[area_code]
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update contacts set dnc_checked_at = now(), dnc_registry = %s "
                    "where id = %s",
                    (hit, contact_id),
                )
                append_event(
                    cur, "system", "contact.dnc_checked", datetime.now(UTC),
                    {"registry_version": version, "hit": hit},
                    external_id=f"dnc:{contact_id}:{version}",
                    contact_id=contact_id,
                )
                if hit and owner_id != HOUSE_PARTNER_ID:
                    # S-9: a listed number leaves its assignment immediately.
                    set_owner(
                        cur, contact_id, HOUSE_PARTNER_ID,
                        event_type="contact.reclaimed",
                        reason="dnc_registry", actor="system",
                    )
        checked += 1
        if hit:
            hits += 1
        elif already_listed:
            # The delisting writer (S-9): absent from the current version clears
            # the flag with its event — outside the row transaction above because
            # clear_suppression owns its own (the flag update there is idempotent
            # with the one we just wrote).
            clear_suppression(
                contact_id, "dnc_registry",
                reason=f"absent from registry {version}",
                source="system",
                external_id=f"dnc-clear:{contact_id}:{version}",
            )
            cleared += 1
    return DncReport(checked=checked, hits=hits, cleared=cleared)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc_refresh",
        description="Re-scrub contacts in subscribed area codes against the DNC "
        "registry (partner-lead-assignment.md §6/S-9). Runs daily; no-op when "
        "nothing has crossed the 21-day threshold.",
        epilog=(
            "Real runs read a downloaded snapshot directory (see\n"
            "scripts/dnc-download.py; layout marketing/dnc-lists/<YYYY-MM-DD>/ —\n"
            "the directory name is the registry version stamped on check events).\n\n"
            "Examples:\n"
            "  uv run python -m jobs.dnc_refresh --snapshot ../dnc-lists/2026-08-05\n"
            "  uv run python -m jobs.dnc_refresh --fake v1              # empty fake registry\n"
            "  uv run python -m jobs.dnc_refresh --fake v1 --listed 8185550123\n"
            "  uv run python -m jobs.dnc_refresh --fake v1 --limit 100\n\n"
            "Requires OWNER_DATABASE_URL — make targets source .env; this module does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--snapshot", metavar="DIR", default=None,
        help="use the real FileDncRegistry over a downloaded snapshot directory",
    )
    parser.add_argument(
        "--fake", metavar="VERSION", default=None,
        help="use FakeDncRegistry with this version string (no SAN, no network)",
    )
    parser.add_argument(
        "--listed", action="append", default=[], metavar="NATIONAL10",
        help="with --fake: a 10-digit national number the fake registry lists "
        "(repeatable)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="check at most N contacts this run (next N stale, assigned first)",
    )
    args = parser.parse_args(argv)

    if (args.snapshot is None) == (args.fake is None):
        print(
            "dnc_refresh: exactly one of --snapshot DIR (real registry files) or "
            "--fake VERSION (dev) is required.",
            file=sys.stderr,
        )
        return 2

    registry: DncRegistry
    if args.snapshot is not None:
        from pathlib import Path

        from seams.dnc_registry import FileDncRegistry

        registry = FileDncRegistry(Path(args.snapshot))
    else:
        from seams.fakes import FakeDncRegistry

        by_code: dict[str, set[str]] = {}
        for number in args.listed:
            by_code.setdefault(number[:3], set()).add(number)
        registry = FakeDncRegistry(version=args.fake, numbers=by_code)

    report = dnc_refresh(registry, limit=args.limit)
    print(
        f"checked={report.checked} hits={report.hits} cleared={report.cleared}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
