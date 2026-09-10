"""Writer for `dnc_subscriptions` (partner-lead-assignment.md §6, Phase 2) — a
table with no writer is the exact TD-2 shape this feature keeps finding.

Records which area codes the org's registry subscription covers, which is what
bounds the scrub (`jobs/dnc_refresh`). Recording an area code here is a claim
that the SAN subscription at telemarketing.donotcall.gov covers it — the CLI
writes the table, the operator makes the claim true at the portal (the free
five first; $82/area code/year beyond, Phase 0's re-derived set).
"""

import argparse
import sys
from uuid import UUID

from config.params import HOUSE_PARTNER_ID
from db.session import transaction


def _holder_id(name: str | None) -> UUID | None:
    """Resolve --holder to a partner id. None means NMC's own SAN, which is the
    house row — so an unqualified add/remove keeps meaning "our subscription" and
    every existing caller reads the same as before."""
    if name is None:
        return HOUSE_PARTNER_ID
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from partners where name = %s and status = 'active'",
                (name,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def _holder_label(partner_id: UUID, name: str | None) -> str:
    return "NMC (house SAN)" if partner_id == HOUSE_PARTNER_ID else (name or str(partner_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="subscribe_area_codes",
        description="Record the DNC registry subscription's area codes "
        "(partner-lead-assignment.md §6) — the set that bounds jobs/dnc_refresh.",
        epilog=(
            "Examples:\n"
            "  uv run python -m jobs.subscribe_area_codes list\n"
            "  uv run python -m jobs.subscribe_area_codes add 818 747 805\n"
            "  uv run python -m jobs.subscribe_area_codes remove 747\n"
            "  uv run python -m jobs.subscribe_area_codes add 818 --holder 'Jane Doe'\n\n"
            "A code can be covered by NMC's SAN, a partner's own, or both — the\n"
            "holder is part of the record. Without --holder these commands mean\n"
            "NMC's subscription, and remove NEVER drops another holder's row.\n\n"
            "Getting the DNC list for an area code (do this BEFORE `add` — the row\n"
            "here is a claim the portal subscription makes true):\n"
            "  1. Log in at https://telemarketing.donotcall.gov with the org's SAN\n"
            "     (Subscription Account Number; registration requires NMC's EIN).\n"
            "  2. Add the area code to the subscription. First 5 codes are free;\n"
            "     $82/code/year beyond that (FY2026).\n"
            "  3. Download the code's FULL list, then change lists on the scrub\n"
            "     cadence — safe harbor requires a registry version <= 31 days old.\n"
            "  4. Record it here (`add <code>`), then run jobs/dnc_refresh to scrub.\n"
            "  5. Calendar the renewal: subscriptions run 12 months from purchase;\n"
            "     renewal opens 30 days before expiry. An expired SAN stops\n"
            "     dnc_refresh cold.\n"
            "Full context: docs/partner-lead-assignment.md § Access and safe harbor.\n\n"
            "Requires OWNER_DATABASE_URL — make targets source .env; this module "
            "does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_add = sub.add_parser("add", help="record subscribed area codes")
    p_add.add_argument("codes", nargs="+", metavar="CODE")
    p_add.add_argument(
        "--holder", metavar="PARTNER",
        help="the partner whose OWN SAN covers these codes (default: NMC's)",
    )
    p_remove = sub.add_parser("remove", help="drop area codes from the record")
    p_remove.add_argument("codes", nargs="+", metavar="CODE")
    p_remove.add_argument(
        "--holder", metavar="PARTNER",
        help="whose coverage to drop (default: NMC's). Never touches another "
        "holder's row — a partner keeps the codes their own SAN pays for.",
    )
    sub.add_parser("list", help="show the recorded subscription set")
    args = parser.parse_args(argv)

    if args.command in ("add", "remove"):
        bad = [c for c in args.codes if not (c.isdigit() and len(c) == 3)]
        if bad:
            print(f"not 3-digit area codes: {bad}", file=sys.stderr)
            return 2

    holder: UUID | None = None
    if args.command in ("add", "remove"):
        holder = _holder_id(args.holder)
        if holder is None:
            print(f"no active partner named {args.holder!r}", file=sys.stderr)
            return 2

    remaining: list[tuple[str, str]] = []
    with transaction() as conn:
        with conn.cursor() as cur:
            if args.command == "add":
                for code in args.codes:
                    cur.execute(
                        "insert into dnc_subscriptions "
                        "(area_code, san_holder_id, subscribed_at) "
                        "values (%s, %s, now()) "
                        "on conflict (area_code, san_holder_id) do nothing",
                        (code, holder),
                    )
            elif args.command == "remove":
                cur.execute(
                    "delete from dnc_subscriptions where area_code = any(%s) "
                    "and san_holder_id = %s",
                    (args.codes, holder),
                )
                # What still covers these codes: a partial removal must never read
                # as a full one.
                cur.execute(
                    "select s.area_code, p.name, s.san_holder_id "
                    "from dnc_subscriptions s join partners p on p.id = s.san_holder_id "
                    "where s.area_code = any(%s) order by s.area_code",
                    (args.codes,),
                )
                remaining = [
                    (code, _holder_label(holder_id, name))
                    for code, name, holder_id in cur.fetchall()
                ]
            cur.execute(
                "select s.area_code, s.subscribed_at, p.name, s.san_holder_id "
                "from dnc_subscriptions s join partners p on p.id = s.san_holder_id "
                "order by s.area_code, p.name"
            )
            rows = cur.fetchall()

    for code, at, name, holder_id in rows:
        print(f"{code}  {_holder_label(holder_id, name)}  subscribed {at:%Y-%m-%d}")
    for code, label in remaining:
        print(f"{code} is STILL covered by {label}", file=sys.stderr)
    print(f"{len(rows)} coverage row(s) recorded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
