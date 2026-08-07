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

from db.session import transaction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="subscribe_area_codes",
        description="Record the DNC registry subscription's area codes "
        "(partner-lead-assignment.md §6) — the set that bounds jobs/dnc_refresh.",
        epilog=(
            "Examples:\n"
            "  uv run python -m jobs.subscribe_area_codes list\n"
            "  uv run python -m jobs.subscribe_area_codes add 818 747 805\n"
            "  uv run python -m jobs.subscribe_area_codes remove 747\n\n"
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
    p_remove = sub.add_parser("remove", help="drop area codes from the record")
    p_remove.add_argument("codes", nargs="+", metavar="CODE")
    sub.add_parser("list", help="show the recorded subscription set")
    args = parser.parse_args(argv)

    if args.command in ("add", "remove"):
        bad = [c for c in args.codes if not (c.isdigit() and len(c) == 3)]
        if bad:
            print(f"not 3-digit area codes: {bad}", file=sys.stderr)
            return 2

    with transaction() as conn:
        with conn.cursor() as cur:
            if args.command == "add":
                for code in args.codes:
                    cur.execute(
                        "insert into dnc_subscriptions (area_code, subscribed_at) "
                        "values (%s, now()) on conflict (area_code) do nothing",
                        (code,),
                    )
            elif args.command == "remove":
                cur.execute(
                    "delete from dnc_subscriptions where area_code = any(%s)",
                    (args.codes,),
                )
            cur.execute(
                "select area_code, subscribed_at from dnc_subscriptions "
                "order by area_code"
            )
            rows = cur.fetchall()

    for code, at in rows:
        print(f"{code}  subscribed {at:%Y-%m-%d}")
    print(f"{len(rows)} area code(s) recorded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
